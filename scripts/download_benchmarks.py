"""
Download benchmark data (SPY, QQQ) for regime detection
"""
import sys
import asyncio
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dss.ingestion.update_data import DataUpdater


async def main():
    benchmarks = ['SPY', 'QQQ']
    
    print("=" * 80)
    print("DOWNLOADING BENCHMARK DATA")
    print("=" * 80)
    print(f"\nSymbols: {', '.join(benchmarks)}")
    print("Period: Last 5 years")
    print(f"\n{'=' * 80}\n")
    
    updater = DataUpdater()
    
    try:
        await updater.update_all(symbols=benchmarks, force_full=True)
        print(f"\n{'=' * 80}")
        print("DOWNLOAD COMPLETE")
        print("=" * 80)
    
    finally:
        await updater.close()


if __name__ == "__main__":
    asyncio.run(main())
