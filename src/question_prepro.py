import os
import collections
import cn2an
import re
from config import VALID_JSON_PATH, VALID_TABLES_PATH, TEST_JSON_PATH, TEST_TABLES_PATH, TRAIN_JSON_PATH, \
	TRAIN_TABLES_PATH, MODEL_PATH
from utils import read_data

# 正则匹配区
# 用于匹配数量前后常用词汇
REGEX = r'([^零一二两三四五六七八九十百千万亿]{0,2})([零|一|二|两|三|四|五|六|七|八|九|十|百|千|万]+)([^零一二两三四五六七八九十百千万]{0,3})'
# 用于匹配数字
RE_MATCH_LIST = [
	r'([零|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿]+[点|块][零|一|二|两|三|四|五|六|七|八|九|十|百|千]+)',  # 小数
	r'(百分之[一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿|零|0|1|2|3|4|5|6|7|8|9|\.]+)',  # 百分数
	r'([零|一|二|两|三|四|五|六|七|八|九|十|百|千|万|亿]+)'  # 数字并且已经把 多少元一平 中 的＂一平＂剔除了
]
# 匹配年份
YEAR_MAT = re.compile(r"(\d{2,4})年")

# 词表部分
# 匹配到下面的时候替换
GOOD_SET = set([
	'于倍', '于分', '过分', '过块', '招人', '过的', '前的', '过倍', '年月', '到分', '在月', '在亿',
	'概天', '到月', '于元', '在年', '于平', '足平', '过股', '过套', '招位', '前', '前中', '前名', '前个', '前，', '于的', '过毛', '近天',
	'过平', '前家', '过的', '前里', '前最', '到以', '第的', '足或', '和月', '是元', '前大', '在块', '有年', '超，', '些年', '计年', '在倍',
	'月号', '批年', '年', '超套',
	'至日', '过，', '过平', '有年', '，年', '到年', '道年', '月日', '日', '号', '为年', '在的', '共元', '共克', '共个', '费元', '元', '招个',
	'于个', '超册', '场月', '于岁', '过岁', '在周', '为且', '招名', '的克', '是份', '是个', '达平', '我年', '是平', '为的', '为是', '在个', '过枚', '有个',
	'由个', '中个', '在以', '有个', '有集', '到亿', '过的', '止的', '了册', '超的', '聘个', '于集', '给块', '要元', '在号', '在公', '在百', '在元', '米元',
	'道块', '卖元', '要？', '聘名', '到块', '卖块', '过元', '过集', '于枚', '于册', '为人', '是题', '诶号', '了平', '达亿', '有家', '映天', '破亿', '破千',
	'在以', '止个', '和的', '有平', '超亿', '于亿', '超个', '超块', '破元', '超平', '近套', '在平', '些年', '和年', '或月', '了平', '破的', '超倍', '在亿',
	'前中', '前的', '卖元', '超套', '有艘', '超元', '是年', '有册', '要人', '招个', '在枚', '超元',
	'超台', '招人', '超人', '要个', '在集', '卖元', '聘位', '买只'
])

# 数词前面常用的2字前缀
GOOD_SET_2_CHAR = set([
	'大于', '等于', '小于', '超过', '一共', '达到', '达到', '高于', '低于', '不足', '少于',
	'成交', '高过', '不足', '总计', '排名', '名次', '破了', '每股', '过了', '不到', '超过', '年的',
	'最近', '月还', '幅后', '幅前', '没破', '低于', '收费',
	'不到', '多于', '于了', '需要', '每平'
])
GOOD_SET_TAIL_2_CHAR = set([
	'以上', '克的', '块钱', '平米', '多人', '多个', '多名', '每平',
	'每个', '每只', '每双', '毛钱', '月份', '车道', '毫升', '级的'
])

GOOD_SET_TAIL_3_CHAR = set(['亿以上', '平方米', '元以下', '的排行', '个以上', '名以上', '美元以'])

BAD_SET = set([
	'问下', '查下', '解下', '询下', '第季', '说下', '我下', '这本', '共', '这周', '哪个', '查本', '这个', '知下', '问共',
	'第第', '第', '第周', '算下', '了等', '估下',
	'第中', '第医', '哪年', '近周', '算算', '这部', '迹代', '查查', '周手', '珠角', '剧共', '集共', '哪天', '书共', '的季', '近年', '第高', '高的',
	'第步', '和世', '第批', '不不', '交手', '的川', '同时', '上般', '上本', '第章', '新线', '下年'
])

METRIC_DICT = {'十': 10, '百': 100, '千': 1000, '万': 10000}

DIGIT_SET = set(['一', '二', '两', '三', '四', '五', '六', '七', '八', '九', '十'])

DIGIT_DICT = {
	'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100,
	'千': 1000, '万': 10000, '０': 0, '１': 1, '２': 2, '３': 3, '４': 4, '５': 5, '６': 6, '７': 7, '８': 8, '９': 9, '两': 2,
	'壹': 1, '贰': 2, '叁': 3, '肆': 4, '伍': 5, '陆': 6, '柒': 7, '捌': 8, '玖': 9, '拾': 10, '佰': 100, '仟': 1000,
	'萬': 10000, '亿': 100000000
}
BAD_Q = set(['十二五'])


def get_data_and_table():
	"""
	获取所有可用数据和表
	"""
	valid_data, valid_tables = read_data(
		VALID_JSON_PATH,
		VALID_TABLES_PATH
	)  # 4396 1197
	# headers = valid_tables['xxx']['content'][valid_tables['xxxx']['headers'][0]]

	test_data, test_tables = read_data(
		TEST_JSON_PATH,
		TEST_TABLES_PATH
	)

	train_data, train_tables = read_data(
		TRAIN_JSON_PATH,
		TRAIN_TABLES_PATH
	)  # 41522  5013
	all_data = []
	all_data.extend(train_data)
	all_data.extend(valid_data)
	all_data.extend(test_data)

	all_tables = {}
	all_tables.update(train_tables)
	all_tables.update(valid_tables)
	all_tables.update(test_tables)
	return all_data, all_tables


def get_2_word_before_num(num=100):
	"""
	获取数字前最常见的两个字,默认获取top100
	已经人工标注出了几个常用的,放到　good_set_2_char　里面了
	"""
	all_data, all_tables = get_data_and_table()
	word_2_list = []

	for data in all_data:
		question = data['question']
		re_rule_upper = re.compile(REGEX)
		ret_iter = re_rule_upper.finditer(question)
		if ret_iter is None:
			return None
		# iter转置，这样　后续拼接的时候就不用考虑位置错位了
		ret_iter = [iter for iter in ret_iter][::-1]
		for ret in ret_iter:
			word_2_list.append(ret.group(1))
	most_common_2_word = collections.Counter(word_2_list).most_common(num)
	return most_common_2_word


def replace_uppercase_num(question):
	"""
	替换问题中的大小数字
	"""
	re_rule_upper = re.compile(REGEX)
	ret_iter = re_rule_upper.finditer(question)
	if ret_iter is None:
		return None
	# iter转置，这样　后续拼接的时候就不用考虑位置错位了
	ret_iter = [iter for iter in ret_iter][::-1]
	for ret in ret_iter:
		# Note - 对于一个匹配 m ， 返回一个二元组 (m.start(group), m.end(group)) 。 注意如果 group 没有在这个匹配中，就返回 (-1, -1) 。group 默认为0，就是整个匹配。
		match_start, match_end = ret.span()
		match_val = ret.group(2)
		# 左侧匹配部分需要做处理
		left_part = ret.group(1)
		# 下面做漏斗处理
		right_part = ret.group(3)

		if left_part == '':
			left_part = ' '
		if ret.group(3) == '':
			right_part = '   '

		if (left_part[-1].strip() + ret.group(3).strip()[0:1] not in GOOD_SET) and (
				left_part not in GOOD_SET_2_CHAR) and right_part[-3:-1].strip() not in GOOD_SET_TAIL_2_CHAR and \
				right_part[-3:].strip() not in GOOD_SET_TAIL_3_CHAR:
			continue
		try:
			match_trans = cn2an.cn2an(match_val, "normal")
			if match_trans == int(match_trans):
				match_trans = int(match_trans)
		except ValueError:
			try:  # 尝试添加一个"一"
				match_trans = match_val
				1 == 0  # 下面这块先短路吧,,,
				pass
			# match_trans = cn2an.cn2an('一' + match_val, "normal")
			# if match_trans == int(match_trans): match_trans = int(match_trans)
			except:
				try:  # 二十万一平
					match_trans = cn2an.cn2an(match_val[:-1], "normal")
					if match_trans == int(match_trans):
						match_trans = int(match_trans)
				except:
					print(' replace_uppercase_num Exception find {}'.format(match_val))
					continue

		question = question[:match_start] + ret.group(1) + str(match_trans) + ret.group(3) + question[match_end:]
	return question


def is_decimal(num):
	"""
	判断一个数字是否是小数
	"""
	if '.' not in num:
		return False
	val_split = str(num).split('.')
	if len(val_split) != 2:
		return False
	# return True if val_split[0].isdigit() and val_split[1].isdigit() else False
	return val_split[0].isdigit() and val_split[1].isdigit()


def replace_percent(target):
	"""
		将 target 中文百分数转换为数字
		eg:
			input: '增幅百分之二百的股票比降幅百分之二十三的大娘'
			output:  增幅200%的股票比降幅23%的大娘
	"""
	while '百分之' in target:
		start_pos = target.find('百分之')
		pos = start_pos + 3
		num = ''
		for i in range(pos, len(target)):
			if target[i].isnumeric() or target[i] == '.':
				num += target[i]
			else:
				break
		if num == '':
			return target
		if not num.isdigit() and not is_decimal(num) and num not in METRIC_DICT.keys():
			new_num = replace_arabic_number(num)
		elif num in METRIC_DICT.keys():
			new_num = METRIC_DICT.get(num)
		else:
			new_num = num
		target = target.replace('百分之' + num, str(new_num) + '%')
	return target


def replace_arabic_number(target):
	"""
	将小词组中的　中文数字表示　转换为阿拉伯形式
	"""
	if target in set(['个', '十', '百', '千', '万']):
		return target
	# if input_s[0] in set(['个', '十', '百', '千', '万']): return input_s
	if target in BAD_Q:
		return target
	start_idx = 0
	end_idx = len(target) - 1
	for v in target:
		if v not in DIGIT_DICT.keys():
			start_idx += 1
		else:
			break
	for v in target[::-1]:
		if v not in DIGIT_DICT.keys():
			end_idx -= 1
		else:
			break
	center = cn2an.cn2an(target[start_idx: end_idx + 1], "normal")
	if len(str(center).split('.')) > 1 and str(center).split('.')[1] == '0':
		center = int(center)

	left_part = target[0: start_idx]
	right_part = target[end_idx + 1:]
	if left_part == right_part and left_part != '':
		return left_part
	return left_part + str(center) + right_part


def preprocess_cn_2_an(question):
	"""
	更加精准的匹配替换, 将question中的中文数字替换为阿拉伯数字
	"""
	question = question.replace(' ', '')
	question = question.replace('　', '')
	question = question.rstrip()
	# global RE_MATCH_LIST
	re_match_list = RE_MATCH_LIST[0:2]  # 只需要匹配好小数和百分数
	for re_match in re_match_list:
		# re_match　为每个正则表达式
		pattern = re.compile(re_match)
		search_start = 0
		while pattern.search(question, search_start) is not None:
			match_sre = pattern.search(question, search_start)
			match_val = match_sre.group()
			append_part = ''
			except_unwant = False
			if '百分之' in match_val:
				match_val_trans = replace_percent(match_val)
			else:
				try:
					if '块' in match_val:
						match_val = match_val.replace('块', '点')
					match_val_trans = cn2an.cn2an(match_val, 'strict')
				except ValueError:
					try:
						match_val_trans = cn2an.cn2an(match_val[:-1], 'strict')
						append_part = match_val[-1]
					except:
						except_unwant = True
						match_val_trans = match_val
				if not except_unwant:
					if '点' not in match_val and '块' not in match_val:
						match_val_trans = int(match_val_trans)
					match_val_trans = str(match_val_trans) + append_part
			question = question[0: match_sre.start()] + str(match_val_trans) + question[match_sre.end():]
			search_start = match_sre.start() + len(str(match_val_trans))
	question = replace_uppercase_num(question)
	return question


def test_preprocess_cn_2_an():
	"""
	trans_question_acc函数测试
	"""
	assert preprocess_cn_2_an('什么小学的岗位只招一人？') == '什么小学的岗位只招1人？'
	assert preprocess_cn_2_an('这些东西一共二十八万元,请缴费一元即可,或者给百分之三十的一点二返现　') == '这些东西一共280000元,请缴费1元即可,或者给30%的1.2返现'
	assert preprocess_cn_2_an('我问你啊就是那个幕后之王收视率超过了百分之零点九，它是在哪个台播的呀') == '我问你啊就是那个幕后之王收视率超过了0.9%，它是在哪个台播的呀'
	assert preprocess_cn_2_an('想要了解一下这周的换手率低于百分之十八的股票的涨跌幅的情况') == '想要了解一下这周的换手率低于18%的股票的涨跌幅的情况'


def preprocess_short_year(question):
	mat_val = YEAR_MAT.findall(question)
	if mat_val and len(mat_val) == 1 and len(mat_val[0]) == 2:
		question = question.replace('{}年'.format(mat_val[0]), '20{}年'.format(mat_val[0]))
	return question


def get_all_vals_contains_num():
	"""
	获取包含数字的专有名词,数据探查函数
	"""
	train_data, train_tables = read_data(
		TRAIN_JSON_PATH,
		TRAIN_TABLES_PATH
	)  # 41522  5013
	val_set = set([])
	re_rule_upper = re.compile(REGEX)
	all_tables = {}
	all_tables.update(train_tables)
	# all_tables.update(valid_tables)
	# all_tables.update(test_tables)
	for t in all_tables:
		for val in all_tables[t]['all_values']:
			if not val.isnumeric() and len(val) <= 10:
				ret_iter = re_rule_upper.finditer(val)
				if ret_iter is None:
					continue
				for ret in ret_iter:
					if ret.group(1) + ret.group(3) not in GOOD_SET: continue
					val_trans = ret.group(1) + ret.group(2) + ret.group(3)
					val_set.add(val + '||||' + val_trans)
	f = open(os.path.join(MODEL_PATH, 'entity'), 'w')
	for val_pair in val_set:
		f.write(val_pair + '\n')
	f.close()


if __name__ == "__main__":
	test_preprocess_cn_2_an()
