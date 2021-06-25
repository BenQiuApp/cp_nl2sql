import jieba
import re
from question_prepro import preprocess_cn_2_an
from utils import find_num, find_similar

# 正则表达式
RE_BRACKET = "\\(.*?\\)|\\{.*?}|\\[.*?]|（.*?）|%"  # 去掉括号里面的内容
UPPERCASE_NUM_SET = ['零', '一', '两', '三', '四', '五', '六', '七', '八', '九', '十']
UPPERCASE_NUM_DICT = {}
for key, val in enumerate(UPPERCASE_NUM_SET):
	UPPERCASE_NUM_DICT[val] = key


def find_similar_with_num(source, target_list):
	"""
	Advanced find_similar，针对数字匹配字段，优化选取列表
	:param source: 匹配字段
	:param target_list: 选取列表
	:return:
	"""
	if re.findall('[^\d\-\.\%]', source):
		return find_similar(source, target_list)
	else:
		new_target_list = [target for target in target_list if find_num(source, target)[0] >= 1]
		if len(new_target_list) == 0:
			return None
		return new_target_list[0] if len(new_target_list) == 1 else find_similar(source, new_target_list)


class Subsets:
	# @param sets, a list of integer
	# @return a list of lists of integer
	def __init__(self, max_len=5):
		self.max_len = max_len

	def dfs(self, start, sets, result, father_subsets):
		if len(father_subsets) > self.max_len:
			return
		result.append(father_subsets)
		for i in range(start, len(sets)):
			self.dfs(i + 1, sets, result, father_subsets + [sets[i]])

	def subsets(self, sets):
		# none case
		if sets is None:
			return []
		# deep first search
		result = []
		self.dfs(0, sorted(sets), result, [])
		return result


def find_similar_fragment(source, target, mode='input'):
	"""
	从句子s中找与w最相近的片段，
	借助分词工具和ngram的方式尽量精确地确定边界。
	 source : cond value
	 target: question
	 输入和输出的相似度函数不应该相同
	 对于输入来说: 进行自动标注的时候，是按照相邻原则来标记的,所以输入采用的相似度方法是n-gram
	 对于输出来说： xxx
	"""
	cut_list = jieba.lcut(target)
	target_list = [x for x in list(cut_list)]
	if mode == 'output':  # 这里只需要组合最大长度为５吧　
		subsets = Subsets().subsets(cut_list)
		target_list = [''.join(item) for item in subsets if len(item) > 0]
	elif mode == 'input':  # 继续采用之前的匹配方式
		target_list.extend([char for char in target])
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:])])  # 2-gram
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:], cut_list[2:])])  # 3-gram
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:], cut_list[2:], cut_list[3:])])  # 4-gram
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:], cut_list[2:], cut_list[3:], cut_list[4:])])  # 5-gram
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:], cut_list[2:], cut_list[3:], cut_list[4:], cut_list[5:])])  # 6-gram
		target_list.extend([''.join(i) for i in zip(cut_list, cut_list[1:], cut_list[2:], cut_list[3:], cut_list[4:], cut_list[5:], cut_list[6:])])  # 7-gram
	else:
		raise ValueError('Unsupported mode! ')
	return find_similar(source, target_list)


def find_match_value(column, target, val):
	"""
	val 为数字可以通过quesiton的col_name来判断
	通过列名称,找到匹配的位置,,然后顺次找到最近的数字
	:param column: col_name
	:param target: question
	:param val: Unknown
	:return: start_pos: 数字开始位置, end_pos: 数字结束位置, val_num : 数字
	"""
	col_name = re.sub(RE_BRACKET, "", column)
	question = preprocess_cn_2_an(target)
	col_in_question = find_similar_fragment(col_name, question)
	start_idx = 0
	if col_in_question is not None and col_in_question in question:
		start_idx = question.index(col_in_question) + len(col_in_question)
	elif col_in_question is not None:
		# 标题不在question里面,分散在里面
		pass
	else:
		return None, None, None
	pattern = re.compile(r'-\d+\.\d+|-\d+|\d+\.\d+|\d+')
	num_find = pattern.findall(question, start_idx)  # 匹配到标题后的第一个数字
	if num_find is None:
		return None, None, None
	# 第一个数字是我们想要标注的位置,找到他的起始位置
	start_pos = question.find(num_find[0], start_idx)
	end_pos = start_pos + len(num_find[0])
	return start_pos, end_pos, question[start_pos:end_pos]


def find_column_value(col_name, question, val):
	"""
	val 为数字可以通过quesiton的col_name来判断
	通过列名称,找到匹配的位置,,然后顺次找到最近的数字
	Return
		start_pos: 数字开始位置
		end_pos: 数字结束位置
		val_in_q : 数字
	"""
	# col_name中的括号去掉
	col_name = re.sub(RE_BRACKET, "", col_name)
	question = preprocess_cn_2_an(question)
	col_in_question = find_similar_fragment(col_name, question)
	start_idx = 0
	if col_in_question is not None and col_in_question in question:
		start_idx = question.index(col_in_question) + len(col_in_question)
	elif col_in_question is not None:  # 标题不在question里面,分散在里面
		pass
	else:
		return None, None, None
	pattern = re.compile(r'-\d+\.\d+|-\d+|\d+\.\d+|\d+')
	num_find = pattern.findall(question, start_idx)  # 匹配到标题后的第一个数字
	if num_find is None:
		return
	try:
		start_idx = question.find(num_find[0], start_idx)  # 第一个数字是我们想要标注的位置,找到他的起始位置
		end_idx = start_idx + len(num_find[0])
		# print(start_idx,  '\t', end_idx,  '\t', question[start_idx:end_idx])
		return start_idx, end_idx, question[start_idx:end_idx]
	except:
		print('except found')
		return None, None, None


def test_find_column_value():
	question = '收入为-10.5的单位有哪些'
	col_name = '收入'
	word = '-10.5'
	assert find_column_value(col_name, question, word) == (3, 8, '-10.5')

	question = '收入为-100的单位有哪些'
	col_name = '收入'
	word = '-100'
	assert find_column_value(col_name, question, word) == (3, 7, '-100')

	question = '你好啊，我想知道出现次数大于8万，频率还高于0.1的都是什么词来着'
	col_name = '频率'
	val = '0.15666'
	assert find_column_value(col_name, question, val) == (22, 25, '0.1')

	question = '你好啊，我想知道出现次数大于8万，频率还高于4325的都是什么词来着'
	col_name = '频率'
	val = '133'
	assert find_column_value(col_name, question, val) == (22, 26, '4325')

	question = '你好啊，我想知道出现次数大于8万，频率还高于4万的都是什么词来着'
	col_name = '频率'
	val = '133'
	assert find_column_value(col_name, question, val) == (22, 23, '4')

	question = '2020年通车高铁线路中长超过100公里，投资高于100亿的线路叫啥名呀'
	col_name = '线路长度（公里）'

	# "线路名称", "沿线地区", "线路长度（公里）", "投资金额（亿元）"
	val = '100'
	assert find_column_value(col_name, question, val) == (15, 18, '100')

	question = '哪些股票是周涨跌幅小于0或年涨跌幅大于0的？'
	col_name = '投资金额（亿元）'

	# "线路名称", "沿线地区", "线路长度（公里）", "投资金额（亿元）"
	val = '100'
	assert find_column_value(col_name, question, val) == (None, None, None)

	question = '请问在什么时候贷款利率调整前大于6%并且贷款利率调整后大于6%？'
	col_name = '贷款利率调整前'
	# "贷款利率调整前", "贷款利率调整后"
	val = '6'
	assert find_column_value(col_name, question, val) == (16, 17, '6')

	question = '请问在什么时候贷款利率调整前大于6%并且贷款利率调整后大于6%？'
	col_name = '贷款利率调整后'
	# "贷款利率调整前", "贷款利率调整后"
	val = '6'
	assert find_column_value(col_name, question, val) == (29, 30, '6')

	question = '我想知道上周5综艺收视率超过3%的，在湖南台播的都有几个啊'
	col_name = '收视率'  # 百分号也干掉
	word = '0.3'
	assert find_column_value(col_name, question, word) == (14, 15, '3')

	question = '哪些城市的成交面积在本周是低于2的'
	col_name = '本周成交面积'
	word = '1.67'
	assert find_column_value(col_name, question, word) == (15, 16, '2')

	question = '有没有最新股价超过5块一股而且持股数量超过五百万股的模拟组合啊'
	col_name = '持股数量'
	word = '500'
	assert find_column_value(col_name, question, word) == (21, 28, '5000000')

	question = '这周票房达到八千万以上的影片共有几部呀'
	col_name = '本周票房'
	word = '8000'
	assert find_column_value(col_name, question, word) == (6, 14, '80000000')

	question = '电视剧收视率排名前3的都是什么剧啊，是在哪个台播的呀'
	col_name = '排名'
	word = '4'
	assert find_column_value(col_name, question, word) == (9, 10, '3')

	question = '新房成交环比上周大于20%而且累计同比也大于20%的上周平均成交量为多少'
	col_name = '累计同比'
	word = '10'
	assert find_column_value(col_name, question, word) == (22, 24, '20')

	question = '场均人次小于10而且上映了10天以上的电影最大累计票房为多少万'
	col_name = '上映天数'
	word = '10'
	assert find_column_value(col_name, question, word) == (13, 15, '10')


if __name__ == "__main__":
	test_find_column_value()
