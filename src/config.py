import os
import sys

ROOT_DIR = os.path.abspath(os.curdir)

MODEL_PATH = os.path.join(ROOT_DIR, 'data')

BERT_PATH = os.path.join(MODEL_PATH, 'chinese-bert_chinese_wwm_L-12_H-768_A-12')

TRAIN_DATA_PATH = os.path.join(MODEL_PATH, 'train')

TRAIN_JSON_PATH = os.path.join(TRAIN_DATA_PATH, 'train.json')

TRAIN_TABLES_PATH = os.path.join(TRAIN_DATA_PATH, 'train.tables.json')

VALID_DATA_PATH = os.path.join(MODEL_PATH, 'val')

VALID_JSON_PATH = os.path.join(VALID_DATA_PATH, 'val.json')

VALID_TABLES_PATH = os.path.join(VALID_DATA_PATH, 'val.tables.json')

VALID_DATABASE_PATH = os.path.join(VALID_DATA_PATH, 'val.db')

TEST_DATA_PATH = os.path.join(MODEL_PATH, 'test')

TEST_JSON_PATH = os.path.join(TEST_DATA_PATH, 'test.json')

TEST_TABLES_PATH = os.path.join(TEST_DATA_PATH, 'test.tables.json')

TEST_SUBMIT_PATH = os.path.join(ROOT_DIR, 'result.json')

LOG_PATH = os.path.join(MODEL_PATH, 'logs')

PREPARE_DATA_PATH = os.path.join(MODEL_PATH, 'prepare_data')

BERT_CONFIG_PATH = os.path.join(MODEL_PATH, 'bert_config.json')
BERT_CKPT_PATH = os.path.join(MODEL_PATH, 'bert_model.ckpt')
BERT_VOCAB_PATH = os.path.join(MODEL_PATH, 'vocab.txt')

WEIGHT_PATH = os.path.join(MODEL_PATH, 'weights')
WEIGHT_SAVE_PATH = os.path.join(WEIGHT_PATH, 'nl2sql_finetune.weights')

# data to sqlite
AGG_DICT = {0: "", 1: "AVG", 2: "MAX", 3: "MIN", 4: "COUNT", 5: "SUM"}
COND_OP_DICT = {0: ">", 1: "<", 2: "==", 3: "!="}
RELA_DICT = {0: '', 1: ' AND ', 2: ' OR '}

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3


class Config(object):
	def __init__(self, **kwargs):
		for key, value in kwargs.items():
			self.__setattr__(key, value)

	def add_argument(self, key, value):
		self.__setattr__(key, value)


config = Config(
	model_path=MODEL_PATH,
	train_data_path=TRAIN_DATA_PATH,
	valid_data_path=VALID_DATA_PATH,
	test_file_path=TEST_DATA_PATH,
	test_submit_path=TEST_SUBMIT_PATH,
	log_path=LOG_PATH,
	prepare_data_path=PREPARE_DATA_PATH,
	agg_dict=AGG_DICT,
	cond_op_dict=COND_OP_DICT,
	rela_dict=RELA_DICT
)

