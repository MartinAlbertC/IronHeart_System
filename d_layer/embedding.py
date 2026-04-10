# -*- coding: utf-8 -*-
"""
Embedding Engine
使用 sentence-transformers 进行本地向量计算
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
from typing import List, Union, Optional
from sentence_transformers import SentenceTransformer

import config


class EmbeddingEngine:
    """
    Embedding 引擎封装
    支持自动下载模型，并提供余弦相似度计算
    """

    _instance = None  # 单例模式

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        print("=" * 60)
        print("Loading Embedding Model")
        print("=" * 60)
        print(f"Model: {config.EMBEDDING_MODEL_NAME}")
        print("Note: First run may take a moment to download the model...")
        print()

        self.model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()

        print(f"Model loaded successfully!")
        print(f"Embedding dimension: {self.embedding_dim}")
        print("=" * 60)
        print()

        self._initialized = True

    def encode(self, text: str) -> np.ndarray:
        """
        将文本编码为向量

        Args:
            text: 输入文本

        Returns:
            numpy数组，形状为 (embedding_dim,)
        """
        if not text or not text.strip():
            # 返回零向量
            return np.zeros(self.embedding_dim)

        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """
        批量编码文本

        Args:
            texts: 文本列表

        Returns:
            numpy数组，形状为 (len(texts), embedding_dim)
        """
        if not texts:
            return np.array([])

        # 过滤空文本
        valid_texts = [t if t and t.strip() else " " for t in texts]
        embeddings = self.model.encode(valid_texts, convert_to_numpy=True)
        return embeddings

    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        计算两个向量的余弦相似度

        Args:
            vec1: 向量1
            vec2: 向量2

        Returns:
            余弦相似度值 [-1, 1]
        """
        # 处理零向量
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = np.dot(vec1, vec2) / (norm1 * norm2)
        # 确保在有效范围内
        return float(np.clip(similarity, -1.0, 1.0))

    def batch_cosine_similarity(self, query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        """
        计算查询向量与矩阵中所有向量的余弦相似度

        Args:
            query: 查询向量，形状为 (embedding_dim,)
            matrix: 向量矩阵，形状为 (n, embedding_dim)

        Returns:
            相似度数组，形状为 (n,)
        """
        if matrix.size == 0:
            return np.array([])

        # 处理单行情况
        if len(matrix.shape) == 1:
            matrix = matrix.reshape(1, -1)

        # 归一化
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return np.zeros(matrix.shape[0])

        query_normalized = query / query_norm

        # 计算每行的范数
        row_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        # 避免除以零
        row_norms = np.where(row_norms == 0, 1, row_norms)
        matrix_normalized = matrix / row_norms

        # 批量点积
        similarities = np.dot(matrix_normalized, query_normalized)

        return similarities

    def max_cosine_similarity(self, query: np.ndarray, matrix: np.ndarray) -> float:
        """
        计算查询向量与矩阵中向量的最大余弦相似度

        Args:
            query: 查询向量
            matrix: 向量矩阵

        Returns:
            最大相似度值
        """
        similarities = self.batch_cosine_similarity(query, matrix)
        if similarities.size == 0:
            return 0.0
        return float(np.max(similarities))

    def mean_cosine_similarity(self, query: np.ndarray, matrix: np.ndarray) -> float:
        """
        计算查询向量与矩阵中向量的平均余弦相似度

        Args:
            query: 查询向量
            matrix: 向量矩阵

        Returns:
            平均相似度值
        """
        similarities = self.batch_cosine_similarity(query, matrix)
        if similarities.size == 0:
            return 0.0
        return float(np.mean(similarities))


# 全局单例
_engine = None


def get_embedding_engine() -> EmbeddingEngine:
    """获取全局 Embedding 引擎单例"""
    global _engine
    if _engine is None:
        _engine = EmbeddingEngine()
    return _engine
