#!/usr/bin/env python3
"""CLI 主入口 — 水土保持方案自动生成系统。

用法:
    python scripts/run.py \
        --facts config/facts_v2.json \
        --measures config/measures_v2.csv \
        --output data/output/

    # 不使用 LLM (仅计算引擎 + 默认措施 + 占位文本)
    python scripts/run.py --no-llm

    # 指定 vLLM 地址
    python scripts/run.py --vllm-url http://localhost:8000/v1
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 抑制第三方库的过度 DEBUG 输出
    for noisy in ("pdfminer", "chromadb", "httpx", "httpcore",
                   "openai", "urllib3", "onnxruntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(
        description="水土保持方案自动生成系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--facts", type=str,
        default="config/facts_v2.json",
        help="项目概况 JSON 文件路径 (相对于项目根目录)",
    )
    parser.add_argument(
        "--measures", type=str,
        default="config/measures_v2.csv",
        help="已有措施 CSV 文件路径",
    )
    parser.add_argument(
        "--output", type=str,
        default="data/output/",
        help="输出目录路径",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="不使用 LLM，仅运行计算引擎 + 默认措施 + 占位文本",
    )
    parser.add_argument(
        "--vllm-url", type=str, default=None,
        help="vLLM 服务地址 (默认: http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="模型名称 (默认: qwen2.5-7b; Ollama 用 qwen2.5:7b)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志输出",
    )
    parser.add_argument(
        "--build-rag", action="store_true",
        help="先构建 RAG 语料再运行",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger("main")
    logger.info("水土保持方案自动生成系统 v1.0")
    logger.info(f"项目根目录: {PROJECT_ROOT}")

    # 解析路径
    facts_path = PROJECT_ROOT / args.facts
    measures_path = PROJECT_ROOT / args.measures
    output_dir = PROJECT_ROOT / args.output

    # 验证文件存在
    if not facts_path.exists():
        logger.error(f"facts 文件不存在: {facts_path}")
        sys.exit(1)
    if not measures_path.exists():
        logger.error(f"measures 文件不存在: {measures_path}")
        sys.exit(1)

    # 覆盖 vLLM URL / 模型名
    import src.settings as settings
    if args.vllm_url:
        settings.VLLM_URL = args.vllm_url
    if args.model:
        settings.VLLM_MODEL_NAME = args.model

    # 构建 RAG
    if args.build_rag:
        logger.info("构建 RAG 语料...")
        from scripts.build_rag import main as build_rag_main
        build_rag_main()

    # 运行流水线
    from src.pipeline import Pipeline

    pipeline = Pipeline(
        facts_path=facts_path,
        measures_path=measures_path,
        output_dir=output_dir,
        use_llm=not args.no_llm,
    )

    try:
        output_path = pipeline.run()
        logger.info(f"\n{'='*60}")
        logger.info(f"报告生成完毕: {output_path}")
        logger.info(f"{'='*60}")
    except Exception as e:
        logger.error(f"\n流水线执行失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
