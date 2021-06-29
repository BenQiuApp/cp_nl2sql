import os
os.environ['PYTHONHASHSEED'] = '0'
os.environ['TF_KERAS'] = '1'
import argparse
import codecs
import re
import json
import numpy as np
import tensorflow as tf
import tensorflow.keras.backend as K
from keras_bert import load_trained_model_from_checkpoint, Tokenizer
from tensorflow.keras.layers import Input, Lambda, Dense, concatenate
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import Callback
from tqdm import tqdm

from config import BERT_PATH, TRAIN_JSON_PATH, TRAIN_TABLES_PATH, VALID_JSON_PATH, VALID_TABLES_PATH, TEST_JSON_PATH, TEST_TABLES_PATH, TEST_SUBMIT_PATH, LOG_PATH, WEIGHT_SAVE_PATH, PY3, PY2
from calc_acc import check_part_acc
from check_input_feature import find_similar_with_num, find_similar_fragment, find_column_value
from post_treat import smooth_numeric, get_append_unit, REGEX_TAIL, number_trans
from new_mark_acc_ensure import correct_q_set, no_num_similar_set,\
	q_one_vs_more_col_set, q_need_exactly_match_set, q_need_exactly_match_more_strinct_set,\
	q_text_contain_similar_set, q_need_col_similar_set
from question_prepro import preprocess_cn_2_an, preprocess_short_year
from utils import read_data, find_num

parser = argparse.ArgumentParser()
parser.add_argument('--mode', type=str, default='', help='execute mode, eg: train/test/evaluate')
args = parser.parse_args()
if args.mode not in set(['train', 'test', 'evaluate']):
	raise ValueError('Please input correct execute mode')
mode = args.mode

maxlen = 160
num_agg = 7  # agg_sql_dict = {0:"", 1:"AVG", 2:"MAX", 3:"MIN", 4:"COUNT", 5:"SUM", 6:"不被select"}
num_op = 5  # {0:">", 1:"<", 2:"==", 3:"!=", 4:"不被select"}
num_cond_conn_op = 3  # conn_sql_dict = {0:"", 1:"and", 2:"or"}
csel_num = 20  # col cnt 最大为20

# learning_rate = 5e-5
learning_rate = 15e-5  # 8 is Ok and testing 15
min_learning_rate = 1e-5

config_path = os.path.join(BERT_PATH, 'bert_config.json')
checkpoint_path = os.path.join(BERT_PATH, 'bert_model.ckpt')
dict_path = os.path.join(BERT_PATH, 'vocab.txt')

# if mode != 'test':
train_data, train_tables = read_data(
	TRAIN_JSON_PATH,
	TRAIN_TABLES_PATH
)  # 41522  5013

valid_data, valid_tables = read_data(
	VALID_JSON_PATH,
	VALID_TABLES_PATH
)  # 4396 1197

test_data, test_tables = read_data(
	TEST_JSON_PATH,
	TEST_TABLES_PATH
)

token_dict = {}
with codecs.open(dict_path, 'r', 'utf8') as reader:
	for line in reader:
		token = line.strip()
		token_dict[token] = len(token_dict)


class OurTokenizer(Tokenizer):
	def _tokenize(self, text):
		tokens = []
		for c in text:
			if c in self._token_dict:
				tokens.append(c)
			elif self._is_space(c):
				tokens.append('[unused1]')
			else:
				tokens.append('[UNK]')
		return tokens


tokenizer = OurTokenizer(token_dict)


def seq_padding(X, padding=0, max_len=None):
	if max_len is None:
		L = [len(x) for x in X]
		ML = max(L)
	else:
		ML = max_len
	return np.array([
		np.concatenate([x[:ML], [padding] * (ML - len(x))]) if len(x[:ML]) < ML else x for x in X
	])


def seq_gather(x):
	"""
	seq是[None, seq_len, s_size]的格式，
	idxs是[None, n]的格式，在seq的第i个序列中选出第idxs[i]个向量，
	最终输出[None, n, s_size]的向量。
	seq_gather[x, h]
	"""
	seq, idxs = x
	idxs = K.cast(idxs, 'int32')  # must int 32
	return tf.gather(seq, idxs, batch_dims=1)


class DataGenerator:
	def __init__(self, data, tables, batch_size=32):  # 32 to 256 for cpu , 32 for gpu
		self.data = data
		self.tables = tables
		self.batch_size = batch_size
		self.steps = len(self.data) // self.batch_size
		if len(self.data) % self.batch_size != 0:
			self.steps += 1

	def __len__(self):
		return self.steps

	def __iter__(self):
		while True:
			if PY2:
				idxs = range(len(self.data))
			elif PY3:
				idxs = [x for x in range(len(self.data))]
			np.random.shuffle(idxs)
			X1, X2, XM, H, HM, SEL, CONN, CSEL0, COP = [], [], [], [], [], [], [], [], []
			CSEL1, CSEL2 = [], []
			CDIV = []

			for i in idxs:
				temp_data = self.data[i]
				table_id = temp_data['table_id']
				ori_q = temp_data['question']
				question = preprocess_cn_2_an(temp_data['question'])
				# temp_data['question'] = preprocess_cn_2_an(temp_data['question'])
				t_headers = self.tables[table_id]['headers']
				t_types = self.tables[table_id]['types']
				
				# chinese-bert: vocab.txt
				# token_ids, segment_ids
				x1, x2 = tokenizer.encode(question)
				xm = [0] + [1] * len(question) + [0]
				h = []
				for j in t_headers:
					_x1, _x2 = tokenizer.encode(j)
					h.append(len(x1))
					x1.extend(_x1)
					x2.extend(_x2)
				# x1 --> encode(question).extend([encode(headers)])

				hm = [1] * len(h)

				sel = []
				# sql.sel --> sql.agg / num_agg.not_select
				for j in range(len(h)):
					if j in temp_data['sql']['sel']:
						j = temp_data['sql']['sel'].index(j)
						sel.append(temp_data['sql']['agg'][j])
					else:
						# num_agg = 7 agg_sql_dict = {0:"", 1:"AVG", 2:"MAX", 3:"MIN", 4:"COUNT", 5:"SUM", 6:"不被select"}
						sel.append(num_agg - 1)

				conn = [temp_data['sql']['cond_conn_op']]
				csel0 = np.zeros(len(question) + 2, dtype='int32')
				csel1 = np.zeros(len(question) + 2, dtype='int32')
				csel2 = np.zeros(len(question) + 2, dtype='int32')
				cop = np.zeros(len(question) + 2, dtype='int32') + num_op - 1
				cdiv = np.zeros(len(question) + 2, dtype='int32')
				is_wrong_q = False
				for cond in temp_data['sql']['conds']:
					if question in correct_q_set:
						if t_types[cond[0]] == 'real':
							_, start_pos, end_pos = find_num(cond[2], question)
							csel0[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
							cop[start_pos + 1: end_pos + 1 + 1] = cond[1]
						else:
							start_pos = question.index(cond[2]) if cond[2] in question else \
								question.index(find_similar_fragment(cond[2], question))
							# print(start_pos, start_pos + len(cond[2]), d['question'][start_pos: start_pos + len(cond[2])])
							csel0[start_pos + 1: start_pos + 1 + len(cond[2])] = cond[0] + 1
							cop[start_pos + 1: start_pos + 1 + len(cond[2])] = cond[1]
					elif question in no_num_similar_set:
						# print('cond val is{}'.format(cond[2]))
						# print('cond val is {}, q is {}  and sim is {}'.format(cond[2],  find_similar_fragment(cond[2], d['question'])))

						sim = cond[2] if cond[2] in temp_data['question'] else find_similar_fragment(cond[2], temp_data['question'])
						start_pos = temp_data['question'].index(sim)
						# print(d['question'])
						# print(start_pos, start_pos + len(sim), d['question'][start_pos: start_pos + len(sim)])
						csel0[start_pos + 1: start_pos + len(sim) + 1] = cond[0] + 1
						cop[start_pos + 1: start_pos + len(sim) + 1] = cond[1]
					elif temp_data['question'] in q_one_vs_more_col_set:
						# print(d['question'])
						if find_num(cond[2], temp_data['question'])[0] == 1:
							_, start_pos, end_pos = find_num(cond[2], temp_data['question'])
						elif find_num(cond[2], temp_data['question'], False)[0] == 1:
							_, start_pos, end_pos = find_num(cond[2], temp_data['question'], False)
						else:
							raise ValueError('value error')
						if max(csel0[start_pos + 1: end_pos + 1 + 1]) != 0:
							if max(csel1[start_pos + 1: end_pos + 1 + 1]) != 0:
								csel2[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
							else:
								csel1[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
						else:
							csel0[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
						cop[start_pos + 1: end_pos + 1 + 1] = cond[1]
					# print(start_pos, end_pos, d['question'][start_pos: end_pos + 1])

					elif temp_data['question'] in q_need_exactly_match_set:
						_, start_pos, end_pos = find_num(cond[2], temp_data['question'])
						# print(d['question'])
						# print(start_pos, end_pos, d['question'][start_pos: end_pos + 1])
						csel0[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
						cop[start_pos + 1: end_pos + 1 + 1] = cond[1]
					elif temp_data['question'] in q_need_exactly_match_more_strinct_set:
						_, start_pos, end_pos = find_num(cond[2], temp_data['question'], False)
						# print(d['question'])
						# print(start_pos, end_pos, d['question'][start_pos: end_pos + 1])
						csel0[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
						cop[start_pos + 1: end_pos + 1 + 1] = cond[1]

					elif temp_data['question'] in q_text_contain_similar_set:
						if t_types[cond[0]] == 'real':  # 如果是数字的话，通过另外的方法判断
							# print(d['question'])
							find_cnt, start_pos, end_pos = find_num(cond[2], temp_data['question'], False)
							if find_cnt == 1:

								# print(start_pos, end_pos, d['question'][start_pos: end_pos + 1])
								csel0[start_pos + 1: end_pos + 1 + 1] = cond[0] + 1
								cop[start_pos + 1: end_pos + 1 + 1] = cond[1]
							elif find_cnt == 0:
								val = find_similar_fragment(cond[2], temp_data['question'])
								start_pos = temp_data['question'].index(val)
								# print(start_pos, start_pos + len(sim), d['question'][start_pos: start_pos + len(sim)])
								csel0[start_pos + 1: start_pos + len(val) + 1] = cond[0] + 1
								cop[start_pos + 1: start_pos + len(val) + 1] = cond[1]

						else:  # 文本
							val = find_similar_fragment(cond[2], temp_data['question'])
							start_pos = temp_data['question'].index(val)
							# print(start_pos, start_pos + len(sim), d['question'][start_pos: start_pos + len(sim)])
							csel0[start_pos + 1: start_pos + len(val) + 1] = cond[0] + 1
							cop[start_pos + 1: start_pos + len(val) + 1] = cond[1]

					elif temp_data['question'] in q_need_col_similar_set:
						header_name = t_headers[cond[0]]
						start_pos, end_pos, match_val = find_column_value(header_name, temp_data['question'], cond[2])
						csel0[start_pos + 1: end_pos + 1] = cond[0] + 1
						cop[start_pos + 1: end_pos + 1] = cond[1]
					else:
						is_wrong_q = True
					ab = True
					if ab:
						for idx in range(1, len(csel0) - 1):
							if csel0[idx] != csel0[idx - 1] and csel0[idx - 1] != 0 and csel0[idx] != 0:
								# print(d['question'])
								cdiv[idx] = 1
							# print(cdiv)

				if len(x1) > maxlen or is_wrong_q:
					continue
				X1.append(x1)  # bert的输入
				X2.append(x2)  # bert的输入
				XM.append(xm)  # 输入序列的mask
				H.append(h)  # 列名所在位置
				HM.append(hm)  # 列名mask
				SEL.append(sel)  # 被select的列
				CONN.append(conn)  # 连接类型
				CSEL0.append(csel0)  # 条件中的列
				CSEL1.append(csel1)  # 条件中的列
				CSEL2.append(csel2)  # 条件中的列
				COP.append(cop)  # 条件中的运算符（同时也是值的标记）
				CDIV.append(cdiv)  #
				if len(X1) == self.batch_size:
					X1 = seq_padding(X1)
					X2 = seq_padding(X2)
					XM = seq_padding(XM, max_len=X1.shape[1])
					H = seq_padding(H)
					HM = seq_padding(HM)
					SEL = seq_padding(SEL)
					CONN = seq_padding(CONN)
					CSEL0 = seq_padding(CSEL0, max_len=X1.shape[1])
					CSEL1 = seq_padding(CSEL1, max_len=X1.shape[1])
					CSEL2 = seq_padding(CSEL2, max_len=X1.shape[1])
					CDIV = seq_padding(CDIV, max_len=X1.shape[1])

					COP = seq_padding(COP, max_len=X1.shape[1])
					yield [X1, X2, XM, H, HM, SEL, CONN, CSEL0, CSEL1, CSEL2, COP, CDIV], None
					X1, X2, XM, H, HM, SEL, CONN, CSEL0, COP = [], [], [], [], [], [], [], [], []
					CSEL1, CSEL2 = [], []
					CDIV = []
				else:
					pass


train_D = DataGenerator(train_data, train_tables)  # get Train data
# valid_D = data_generator(valid_data, valid_tables)  #get Train data

bert_model = load_trained_model_from_checkpoint(config_path, checkpoint_path, seq_len=None)

for l in bert_model.layers:
	l.trainable = True

x1_in = Input(shape=(None,), dtype='int32')
x2_in = Input(shape=(None,))
xm_in = Input(shape=(None,))
h_in = Input(shape=(None,), dtype='int32')
hm_in = Input(shape=(None,))
sel_in = Input(shape=(None,), dtype='int32')
conn_in = Input(shape=(1,), dtype='int32')
csel0_in = Input(shape=(None,), dtype='int32')
csel1_in = Input(shape=(None,), dtype='int32')
csel2_in = Input(shape=(None,), dtype='int32')
cop_in = Input(shape=(None,), dtype='int32')
cdiv_in = Input(shape=(None,), dtype='int32')

x1, x2, xm, h, hm, sel, conn, csel0, csel1, csel2, cop, cdiv = (
	x1_in, x2_in, xm_in, h_in, hm_in, sel_in, conn_in, csel0_in, csel1_in, csel2_in, cop_in, cdiv_in
)

hm = Lambda(lambda x: K.expand_dims(x, 1))(hm)  # header的mask.shape=(None, 1, h_len)

x = bert_model([x1_in, x2_in])  # shape x [?, ?, 768] [batch_size, n_step(n_input_step), hidden_size]
x4conn = Lambda(lambda x: x[:, 0])(x)  # x[:, 0] [None, hidden_size]
pconn = Dense(num_cond_conn_op, activation='softmax')(x4conn)  # [None, num_cond_conn_op]

# h记录各个header[cls]所在的位置, 这个seq_gather的作用就是把input_x中的header[cls]搞出来。
x4h = Lambda(seq_gather)([x, h])  # header [cls] is selected  [batch_size, header_step, hidden_size]
psel = Dense(num_agg, activation='softmax')(x4h)  # [bs, header_step, num_agg]

pcop = Dense(num_op, activation='softmax')(x)  # [bs, q_step, num_op]

x_ori = x
x = Lambda(lambda x: K.expand_dims(x, 2))(x)  # shape [batch_size, n_step, 1, hidden_size]
x4h_ori = x4h
x4h = Lambda(lambda x: K.expand_dims(x, 1))(x4h)  # header cls selected in x4h  [None, 1, header_n_step, hidden_size ]

pcsel_1 = Dense(1)(x)  # [None, q_n_step, 1 ,1]
pcsel_2 = Dense(1)(x4h)  # [None, 1, h_n_step, 1 ]
pcsel_att = Lambda(lambda x: x[0] * x[1])([pcsel_1, pcsel_2])  # [None, q_n_step, h_n_step,1]
pcsel_att = Lambda(lambda x: x[..., 0])(pcsel_att)  # [None,q_n_step，h_n_step]
# x4h_ori  [None, h_n_step，hidden_size】
pcsel_h_part = Lambda(lambda x: K.batch_dot(x[0], x[1]))([pcsel_att, x4h_ori])  # [None, q_n_step, hidden_siz]
pcsel = concatenate([x_ori, pcsel_h_part], axis=-1)

pcsel = Dense(1200, activation='relu')(pcsel)  # [None, q_n_step, 1200]
pcdiv = Dense(2, activation='softmax')(pcsel)

pcsel0 = Dense(csel_num, activation='softmax')(pcsel)  # [bs, q_step, 3, num_op]
pcsel1 = Dense(csel_num, activation='softmax')(pcsel)  # [bs, q_step, 3, num_op]
pcsel2 = Dense(csel_num, activation='softmax')(pcsel)  # [bs, q_step, 3, num_op]

# Model的参数    def __init__(self, inputs, outputs, name=None):
model = Model(
	[x1_in, x2_in, h_in, hm_in],  # inputs
	[psel, pconn, pcop, pcsel0, pcsel1, pcsel2, pcdiv]  # outputs
)

train_model = Model(
	[x1_in, x2_in, xm_in, h_in, hm_in, sel_in, conn_in, csel0_in, csel1_in, csel2_in, cop_in, cdiv_in],
	[psel, pconn, pcop, pcsel0, pcsel1, pcsel2, pcdiv]
)

xm = xm  # question的mask.shape=(None, x_len)

hm = hm[:, 0]  # header的mask.shape=(None, h_len)  # 这个操作就是去掉1，torch中有squeeze压紧方法做这个事情

# condition mask, [1, 0, 1, 1,1 ] 如果元素为1，说明当前位置的op不是空操作
cm = K.cast(K.not_equal(cop, num_op - 1), 'float32')  # conds 的 mask.shape=(None, x_len)

# 注意hm & xm 用在啥地方了

'''
例子1：
   以psel_loss = K.sum(psel_loss * hm) / K.sum(hm) 为例介绍这里的hm的用处.
首先 hm作为header mask, 里面存储的都是header[cls]的位置
     hm的shape为[bs, header_cnt],　header_cnt这个维度里面的值有一些padding的0 
     psel_loss 的shape为 [bs, header_cnt] ? 
     psel_loss * hm 的shape为　[bs, header_cnt]　相乘之后即只关注有效header的损失，那些padding出来的不要加入损失计算
     k.sum(psel_loss * hm) keras.backend中的sum和普通的sum不同，他会将矩阵中的所有值相加，最后结果为一个值

几乎所有参数都是带有batch_size维度的，因为计算损失是在整个batch上计算的
'''
psel_loss = K.sparse_categorical_crossentropy(sel_in, psel)
psel_loss = K.sum(psel_loss * hm) / K.sum(hm)  # case: test10  padding位置的header不纳入损失计算
pconn_loss = K.sparse_categorical_crossentropy(conn_in, pconn)
pconn_loss = K.mean(pconn_loss)  # 取均值，是为了算在整个batch中的损失
pcop_loss = K.sparse_categorical_crossentropy(cop_in, pcop)
pcop_loss = K.sum(pcop_loss * xm) / K.sum(xm)

pcsel0_loss = K.sparse_categorical_crossentropy(csel0_in, pcsel0)
pcsel0_loss = K.sum(pcsel0_loss * xm * cm) / K.sum(xm * cm)

pcsel1_loss = K.sparse_categorical_crossentropy(csel1_in, pcsel1)
pcsel1_loss = K.sum(pcsel1_loss * xm * cm) / K.sum(xm * cm)

pcsel2_loss = K.sparse_categorical_crossentropy(csel2_in, pcsel2)
pcsel2_loss = K.sum(pcsel2_loss * xm * cm) / K.sum(xm * cm)

pcdiv_loss = K.sparse_categorical_crossentropy(cdiv_in, pcdiv)
pcdiv_loss = K.sum(pcdiv_loss * xm * cm) / K.sum(xm * cm)

loss = psel_loss + pconn_loss + pcop_loss + pcsel0_loss + pcsel1_loss + pcsel2_loss + pcdiv_loss

train_model.add_loss(loss)
train_model.compile(optimizer=Adam(learning_rate))
train_model.summary()
# model.load_weights(weight_save_path) #
except_tr_cnt = 0


def nl2sql(question, table):
	"""
	输入question和headers，转SQL
	"""
	try:
		question = preprocess_cn_2_an(question)
		question = preprocess_short_year(question)
		question = question.replace('负数', '小于0')
		question = question.replace('负值', '小于0')
		question = question.replace('为负', '小于0')
		question = question.replace('正数', '大于0')
		question = question.replace('正值', '大于0')
		question = question.replace('为正', '大于0')
		question = question.replace('没什么要求', '不限')
		question = question.replace('没要求', '不限')
	except:
		pass
	x1, x2 = tokenizer.encode(question)
	h = []
	for i in table['headers']:
		_x1, _x2 = tokenizer.encode(i)
		# h这里记录了每个header的[cls]所在位置
		h.append(len(x1))
		x1.extend(_x1)
		x2.extend(_x2)
	hm = [1] * len(h)  # hm为header在[cls]位置的mask, hm的长度，正好是header的个数，当然header的个数和[cls]的个数是一致的

	psel, pconn, pcop, pcsel0, pcsel1, pcsel2, pcdiv = model.predict([
		np.array([x1]),
		np.array([x2]),
		np.array([h]),
		np.array([hm])
	])
	pcsel_ori = pcsel

	R = {'agg': [], 'sel': []}
	# psel是对header的[CLS]位置做处理的出来的，各个header的聚合或者是否被select的概率。
	# psel shape [1, 9, 7] => [None, header_col_cnt, op]
	for i, j in enumerate(psel[0].argmax(1)):
		if j != num_agg - 1:  # num_agg-1类是不被select的意思
			# 7中状态拆分成下面两种，1种是是否被选择，另外一种是agg operation
			R['sel'].append(i)
			R['agg'].append(j)
	conds = []
	v_op = -1

	# pcop: shape [bs, seq_len(n_step), num_op] 下面截取了:len(question) + 1
	# 截取之后shape: [bs, question_len]
	# 在这里的bs=1, 貌似是对每一个样例做的处理.
	# pcop (1, 103, 5) => [None, question+header_len, op_len]
	# 这里的pcop的第二个维度为105
	# 105 =  32(question len) + 2(question cls&sep)+ 53(all header col len) +18(header cls+sep,total 9 column in table)
	# 下面取的时候只取了 [0:33]

	unit_first_list = []
	unit_second_list = []
	for i, j in enumerate(pcop[0, :len(question) + 1].argmax(1)):  # [,,op_cnt]
		# 这里结合标注和分类来预测条件
		if i == 0: continue  # start 0 is of no use
		if j != num_op - 1:  # num_op: {0:">", 1:"<", 2:"==", 3:"!=", 4:"不被select"}
			if v_op != j:
				if v_op != -1:
					v_end = v_start + len(v_str)
					v_start_idx, v_end_idx, smooth_val = smooth_numeric(v_start - 1, v_end - 1, question)
					unit_first, unit_second = get_append_unit(v_start - 1, v_end - 1, question)  # unit_firt: 亿 unit_second: 元
					# 添加div中的信息
					# print(max(pcdiv[0][v_start: v_end].argmax(1)))
					if max(pcdiv[0][v_start: v_end].argmax(1)) > 0:  # 0
						if 1 in pcdiv[0][v_start: v_end].argmax(1):

							entity_start_pos_list = [v_start + 1 + idx for idx, mark in
																			 enumerate(pcdiv[0][v_start + 1: v_end].argmax(1)) if mark == 1]
							if len(entity_start_pos_list) > 0 and entity_start_pos_list[0] != v_start:
								entity_start_pos_list.insert(0, v_start)
							if len(entity_start_pos_list) > 0 and entity_start_pos_list[-1] != v_end:
								entity_start_pos_list.append(v_end)

							for idx in range(len(entity_start_pos_list) - 1):
								new_s = entity_start_pos_list[idx]
								new_e = entity_start_pos_list[idx + 1]
								csel = pcsel0[0][new_s: new_e].mean(0).argmax() - 1
								v_str1 = question[new_s - 1: new_e - 1]
								if v_str1 is not None and csel >= 0:
									unit_first_list.append(unit_first)
									unit_second_list.append(unit_second)
									conds.append((csel, v_op, v_str1))
					else:
						csel = pcsel0[0][v_start: v_end].mean(0).argmax() - 1

						if v_str is not None:
							v_str = smooth_val
							unit_first_list.append(unit_first)
							unit_second_list.append(unit_second)
							conds.append((csel, v_op, v_str))
						if pcsel1[0][v_start: v_end].mean(0).argmax() - 1 >= 0:  # add
							csel = pcsel1[0][v_start: v_end].mean(0).argmax() - 1
							if csel >= 0:
								if v_str is not None:
									v_str = smooth_val
									unit_first_list.append(unit_first)
									unit_second_list.append(unit_second)
									conds.append((csel, v_op, v_str))

						if pcsel2[0][v_start: v_end].mean(0).argmax() - 1 > 0:  # add
							csel = pcsel2[0][v_start: v_end].mean(0).argmax() - 1
							if v_str is not None:
								v_str = smooth_val
								unit_first_list.append(unit_first)
								unit_second_list.append(unit_second)
								conds.append((csel, v_op, v_str))
				v_start = i
				v_op = j  # v_op在这里第一次赋值
				v_str = question[i - 1]  # v_str在这里第一次赋值
			else:  # 在 这里 j == num_op-1,说明当前运算符在question上延续着
				v_str += question[i - 1]
			if i == len(question):
				v_end = v_start + len(v_str)

				v_start_idx, v_end_idx, smooth_val = smooth_numeric(v_start - 1, v_end - 1, question)
				unit_first, unit_second = get_append_unit(v_start - 1, v_end - 1, question)  # unit_firt: 亿 unit_second: 元
				# 添加div中的信息
				# print(max(pcdiv[0][v_start: v_end].argmax(1)))
				if max(pcdiv[0][v_start: v_end].argmax(1)) > 0:  # 0
					if 1 in pcdiv[0][v_start: v_end].argmax(1):
						entity_start_pos_list = [v_start + 1 + idx for idx, mark in
																		 enumerate(pcdiv[0][v_start + 1: v_end].argmax(1)) if mark == 1]
						if len(entity_start_pos_list) > 0 and entity_start_pos_list[0] != v_start:
							entity_start_pos_list.insert(0, v_start)
						if len(entity_start_pos_list) > 0 and entity_start_pos_list[-1] != v_end:
							entity_start_pos_list.append(v_end)

						for idx in range(len(entity_start_pos_list) - 1):
							new_s = entity_start_pos_list[idx]
							new_e = entity_start_pos_list[idx + 1]
							csel = pcsel0[0][new_s: new_e].mean(0).argmax() - 1
							v_str1 = question[new_s - 1: new_e - 1]
							if v_str1 is not None and csel >= 0:
								unit_first_list.append(unit_first)
								unit_second_list.append(unit_second)
								conds.append((csel, v_op, v_str1))
				else:
					if pcsel1[0][v_start: v_end].mean(0).argmax() - 1 >= 0:  # add
						csel = pcsel1[0][v_start: v_end].mean(0).argmax() - 1
						if csel >= 0:
							if v_str is not None:
								v_str = smooth_val
								unit_first_list.append(unit_first)
								unit_second_list.append(unit_second)
								conds.append((csel, v_op, v_str))

					if pcsel2[0][v_start: v_end].mean(0).argmax() - 1 >= 0:  # add
						csel = pcsel2[0][v_start: v_end].mean(0).argmax() - 1
						if v_str is not None:
							v_str = smooth_val
							unit_first_list.append(unit_first)
							unit_second_list.append(unit_second)
							conds.append((csel, v_op, v_str))

					csel = pcsel0[0][v_start: v_end].mean(0).argmax() - 1
					if v_str is not None:
						v_str = smooth_val
						unit_first_list.append(unit_first)
						unit_second_list.append(unit_second)
						conds.append((csel, v_op, v_str))
						break
		elif v_op != -1:  # 遇到了"not selected" 了
			v_end = v_start + len(v_str)
			# pcsel (1, 105, 9) => (None, q_len+h_len, col_cnt )
			# 第二个维度为105, 105 =  32(question len)+2(question cls&sep)+ 53(all header col len) +18(header cls+sep,total 9 column in table
			# pcsel的作用是定位question中的每个字段对应header中的哪个列,所以最后一维为9,当前测试样例的表有９列
			v_start_idx, v_end_idx, smooth_val = smooth_numeric(v_start - 1, v_end - 1, question)
			unit_first, unit_second = get_append_unit(v_start - 1, v_end - 1, question)  # unit_firt: 亿 unit_second: 元
			if max(pcdiv[0][v_start: v_end].argmax(1)) > 0:
				if 1 in pcdiv[0][v_start: v_end].argmax(1) and pcdiv[0][v_start].argmax() != 1:

					entity_start_pos_list = [v_start + 1 + idx for idx, mark in enumerate(pcdiv[0][v_start + 1: v_end].argmax(1))
																	 if mark == 1]
					if entity_start_pos_list[0] != v_start:
						entity_start_pos_list.insert(0, v_start)
					if entity_start_pos_list[-1] != v_end:
						entity_start_pos_list.append(v_end)

					for idx in range(len(entity_start_pos_list) - 1):
						new_s = entity_start_pos_list[idx]
						new_e = entity_start_pos_list[idx + 1]

						csel = pcsel0[0][new_s: new_e].mean(0).argmax() - 1
						v_str1 = question[new_s - 1: new_e - 1]
						if v_str1 is not None and csel >= 0:
							unit_first_list.append(unit_first)
							unit_second_list.append(unit_second)
							conds.append((csel, v_op, v_str1))
			else:
				csel = pcsel0[0][v_start: v_end].mean(0).argmax() - 1
				v_e = v_end - 1
				untreat_unit = ''
				if v_e < len(question) and len(re.findall(REGEX_TAIL, question[v_e])) > 0:
					untreat_unit = re.findall(REGEX_TAIL, question[v_e])[0]
					if v_e + 1 < len(question) and len(re.findall(REGEX_TAIL, question[v_e + 1])) > 0:
						untreat_unit += re.findall(REGEX_TAIL, question[v_e + 1])[0]
				if v_str is not None:
					v_str = smooth_val
					unit_first_list.append(unit_first)
					unit_second_list.append(unit_second)
					conds.append((csel, v_op, v_str))

				if pcsel1[0][v_start: v_end].mean(0).argmax() - 1 >= 0:  # add
					csel = pcsel1[0][v_start: v_end].mean(0).argmax() - 1
					if csel >= 0:
						if v_str is not None:
							v_str = smooth_val
							unit_first_list.append(unit_first)
							unit_second_list.append(unit_second)
							conds.append((csel, v_op, v_str))

				if pcsel2[0][v_start: v_end].mean(0).argmax() - 1 >= 0:  # add
					csel = pcsel2[0][v_start: v_end].mean(0).argmax() - 1
					if v_str is not None:
						v_str = smooth_val
						unit_first_list.append(unit_first)
						unit_second_list.append(unit_second)
						conds.append((csel, v_op, v_str))
			v_op = -1
	R['conds'] = set()  # 集合自己去重
	idx = 0
	for i, j, k in conds:
		if re.findall('[^\d\-\.\%]', k):  # 找到非数字
			j = 2  # 非数字只能用等号,,
		if j == 2:  # 这里判定出条件运算符是等号哦  等号也有可能是数字的
			ori_k = k
			if k not in table['all_values']:
				k = find_similar_with_num(k, list(table['all_values']))
				if k is None: continue
			idx_except = False
			try:
				h = table['headers'][i]
			except:
				h = table['headers'][0]
			# 然后检查值对应的列是否正确，如果不正确，直接修正列名
			if k not in table['content'][h]:  # 发现标记出来的值不在预测出来所属的列不一致。
				for r, v in table['content'].items():
					if k in v:
						i = table['header2id'][r]
						break
		unit_first = None if unit_first_list[idx] == '' else unit_first_list[idx]
		unit_second = None if unit_second_list[idx] == '' else unit_second_list[idx]
		idx += 1
		if k.isnumeric() and i <= len(table['headers']) - 1:  ## 需要改　不要用 isnumeric() 并要处理百分号
			# 添加一个预处理，预测的数字左右缺失的话
			ori_k = k
			try:
				k = number_trans(int(k), table['headers'][i], table['title'], format_of_number=unit_first, format_desc=unit_second)
				max_col_val = None
				have_text_in_col = False
				for col_val in table['content'][table['headers'][i]]:
					if not re.findall('[^\d\.]', str(col_val)):
						if max_col_val is None:
							max_col_val = float(col_val)
						else:
							max_col_val = max(max_col_val, float(col_val))
					else:
						have_text_in_col = True
						break
			except:
				pass
			# 这里如果k是　数字的话，包含百分数，那么去掉后面的百分号
		if not re.findall('[^\d\-\.\%]', str(k)) and '%' in str(k):
			k = str(k)[:-1]
		R['conds'].add((i, j, k))
	if max(pcsel2[0][1:len(question) + 1].argmax(1)) > 0:
		pass
	R['conds'] = list(R['conds'])
	if len(R['conds']) <= 1:  # 条件数少于等于1时，条件连接符直接为0
		R['cond_conn_op'] = 0
	else:
		R['cond_conn_op'] = 1 + pconn[0, 1:].argmax()  # 不能是0
	return R


def evaluate(data, tables):
	pbar = tqdm()
	open_path = os.path.join(LOG_PATH, 'evaluate_pred.json')
	F = open(open_path, mode='w')
	pred_sql_list = []
	gd_sql_list = []
	tables_list = []

	for i, d in enumerate(data):
		question = d['question']
		table = tables[d['table_id']]
		R = nl2sql(question, table)  #
		# print("predicted is {}\n".format(R))
		gd_sql_list.append(d['sql'])
		pred_sql_list.append(R)
		tables_list.append(d['table_id'])
		pbar.update(1)
		d['sql_pred'] = R

		if PY2:
			s = json.dumps(d, ensure_ascii=False)  # add str
			F.write(s.encode('utf-8') + '\n')
		elif PY3:
			s = json.dumps(eval(str(R)), ensure_ascii=False)
			F.write(s + '\n')  #
	F.close()
	acc = check_part_acc(pred_sql_list, gd_sql_list, tables_list, data)
	print(' Acc in evaluate data set is {}'.format(1 - acc[-1]))  # data here is valid data
	pbar.close()
	return 1 - acc[-1]


if mode == 'evaluate':
	# model.load_weights(weight_save_path) #
	evaluate(valid_data, valid_tables)
	import sys
	sys.exit(0)


def test(data, tables, submit_path):
	pbar = tqdm()
	model.load_weights(WEIGHT_SAVE_PATH)  #
	F = open(submit_path, 'w')
	for i, d in enumerate(data):
		question = d['question']
		table = tables[d['table_id']]
		R = nl2sql(question, table)
		pbar.update(1)
		if PY2:
			s = json.dumps(R, ensure_ascii=False)
			F.write(s.encode('utf-8') + '\n')
		elif PY3:
			sql_pred = eval(str(R))
			F.writelines(json.dumps(sql_pred, ensure_ascii=False) + '\n')
	F.close()
	pbar.close()


if mode == 'test':
	print("Start create test result ....")
	# submit_path = '../submit/submit-{}.json'.format(time.strftime('%Y-%m-%d_%H:%M:%S', time.localtime(time.time())))
	test(test_data, test_tables, TEST_SUBMIT_PATH)  # add by shuai  should used !!!!!
	print('Finish create test result and saved in {}'.format(TEST_SUBMIT_PATH))
	import sys
	sys.exit(0)


class MyCallback(Callback):
	def __init__(self):
		print('Evaluate - __init__')
		# self.accs = []
		self.best = 0
		self.passed = 0
		self.stage = 0

	def on_batch_begin(self, batch, logs=None):
		"""
		第一个epoch用来warmup，第二个epoch把学习率降到最低
		"""
		print('Evaluate - on_batch_begin')
		if self.passed < self.params['steps']:
			lr = (self.passed + 1.) / self.params['steps'] * learning_rate
			K.set_value(self.model.optimizer.lr, lr)
			self.passed += 1
		elif self.params['steps'] <= self.passed < self.params['steps'] * 2:
			lr = (2 - (self.passed + 1.) / self.params['steps']) * (learning_rate - min_learning_rate)
			lr += min_learning_rate
			K.set_value(self.model.optimizer.lr, lr)
			self.passed += 1

	def on_epoch_end(self, epoch, logs=None):
		print('Evaluate - on_epoch_end')
		acc = evaluate(valid_data, valid_tables)
		# self.accs.append(acc)
		if acc >= self.best:
			self.best = acc
			train_model.save_weights(WEIGHT_SAVE_PATH)
		print('acc: %.5f, best acc: %.5f\n' % (acc, self.best))


callback = MyCallback()

if __name__ == '__main__':
	print('train_model.fit_generator')
	train_model.fit_generator(
		train_D.__iter__(),
		steps_per_epoch=len(train_D),
		epochs=40,
		callbacks=[callback]
	)
else:
	print('train_model.load_weights')
	train_model.load_weights(WEIGHT_SAVE_PATH)
