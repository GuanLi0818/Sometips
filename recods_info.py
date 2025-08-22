# -*- coding: utf-8 -*-
"""
@File    : recods_info.py
@Author  : qy
@Date    : 2025/8/22 13:16
"""
import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = "data/company_records.jsonl"  # 改成 jsonl 文件，每行一条记录

def save_record(record: dict):
    """把一条记录追加写入文件，每行一个 JSON 对象"""
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"保存记录失败: {e}")

def load_records() -> list:
    """启动时从文件恢复数据，返回列表"""
    records = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception as e:
            logger.error(f"加载记录失败: {e}")
    return records
