import json
import editdistance
import numpy as np


def read_data(data_file, table_file):
	data, tables = [], {}
	with open(data_file, encoding='UTF-8') as file:
		for line in file:
			data.append(json.loads(line))

	with open(table_file, encoding='UTF-8') as file:
		for line in file:
			line = json.loads(line)
			temp = {}
			temp['headers'] = line['header']
			temp['header2id'] = {j: i for i, j in enumerate(temp['headers'])}
			temp['content'] = {}
			temp['keywords'] = {}
			temp['all_values'] = set()
			temp['types'] = line['types']
			temp['title'] = line['title']
			rows = np.array(line['rows'])
			for i, h in enumerate(temp['headers']):
				temp['content'][h] = set(rows[:, i])
				if temp['types'][i] == 'text':
					temp['keywords'][i] = ''
				else:
					temp['keywords'][i] = ''
				temp['all_values'].update(temp['content'][h])
			temp['all_values'] = set([i for i in temp['all_values'] if hasattr(i, '__len__')])
			tables[line['id']] = temp
	return data, tables


def find_num(val, target, ignore_ending_zero=True):
	"""
	数值精确匹配
	:param val: num value
	:param target: target string
	:param ignore_ending_zero: ignore zeros in the ending. True -> val00.. is acceptable
	:return: match_count: 匹配个数, match_start_idx, match_end_idx: 匹配位置
	"""
	num = str(val)
	find_start = 0
	match_count, match_start_idx, match_end_idx = 0, 0, 0
	while target.find(num, find_start) != -1:
		find_start = target.index(num, find_start)
		temp_start_idx = find_start - 1
		temp_end_idx = find_start + len(num)

		while temp_start_idx >= 0 and target[temp_start_idx].isdigit():
			temp_start_idx -= 1
		while temp_end_idx < len(target) and target[temp_end_idx].isdigit():
			temp_end_idx += 1

		if ignore_ending_zero:
			if temp_start_idx >= find_start - 1 and \
					not (temp_end_idx > find_start + len(num) and (int(target[find_start + len(num): temp_end_idx]) != 0)):
				match_count += 1
				match_start_idx = temp_start_idx + 1
				match_end_idx = temp_end_idx - 1
		else:
			if temp_start_idx >= find_start - 1 and temp_end_idx <= find_start + len(num):
				match_count += 1
				match_start_idx = temp_start_idx + 1
				match_end_idx = temp_end_idx - 1

		find_start = temp_end_idx
	return match_count, match_start_idx, match_end_idx


def find_similar(source, target_list):
	"""
	从词表中找最相近的词（当无法全匹配的时候）
	这里做了修正，如果没有能够匹配的值的话，返回 -1
	Note: 与 most_similar 机制一致，针对结果加权
	"""
	if len(target_list) == 0:
		return None
	s_set = set([item for item in source])
	contain_score = []
	un_contain_score = []  # target当中相比于source多出来的部分
	for target in target_list:
		t_set = set([t for t in target])
		contain_score.append(len(s_set & t_set))
		# un_contain_score.append(len(t_set.difference(s_set))) #
		un_contain_score.append(0)
	match_score = [contain_score[idx] * 4 for idx in range(len(target_list))]
	# 如果最高匹配分数为0,说明一个匹配的都没有，返回None
	if max(match_score) == 0:
		return None
	"""
	Former Version:
	edit_score = [len(source) - editdistance.eval(source, t) for t in target_list]
	final_score = [match_score[idx] + edit_score[idx] for idx in range(len(target_list))]
	return target_list[final_score.index(max(final_score))]
	"""
	# 如果匹配分数为0，直接给最小分
	for idx in range(len(target_list)):
		if match_score[idx] == 0:
			match_score[idx] = -65530
	# 下面计算编辑距离分数
	edit_score = [len(source) - editdistance.eval(source, t) for t in target_list]
	final_score = [match_score[idx] + edit_score[idx] for idx in range(len(target_list))]
	return target_list[final_score.index(max(final_score))]


def test_find_num():
	assert find_num(1, '2011年北京排名第1的品牌', True) == (1, 10, 10)
	assert find_num(1, '1年北京排名第11的品牌', True) == (1, 0, 0)
	assert find_num(1, '11年北京排名第11的品牌', True)[0] == 0
	assert find_num(20, '销量大于20吨且盈利大于20万的商品', True)[0] == 2
	assert find_num(11, '11年北京排名第11的品牌', True)[0] == 2
	assert find_num(2, '2020年销量大于20且盈利为2的品牌是啥', True)[0] == 2  ## 这种反例一定要考虑哦
	assert find_num(20, '2020年销量大于20且盈利为2的品牌是啥', True) == (1, 9, 10)


def test_find_num_without_zeros():
	assert find_num(20, '2000年销量大于20且盈利为2的品牌是啥', False) == (1, 9, 10)
	assert find_num(20, '20年来北京卖出2000套且盈利为2的品牌是啥', False) == (1, 0, 1)
	assert find_num(20, '20年来北京卖出2000套且盈利为20%的品牌是啥', False) == (2, 17, 18)
	assert find_num(1000, '19年第1周有哪些电影周票房超过10000000并且票房占比高于10%的？', False) == (0, 0, 0)


if __name__ == "__main__":
	test_find_num()
	test_find_num_without_zeros()
