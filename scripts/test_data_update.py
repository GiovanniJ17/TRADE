"""
Test script to verify data update functionality
"""
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dss.ingestion.update_data import DataUpdater

async def test_data_update():
    """Test data update"""
    
    print("="*80)
    print("TEST DATA UPDATE")
    print("="*80)
    print()
    
    # Initialize updater
    print("Step 1: Initializing DataUpdater...")
    updater = DataUpdater()
    print("[OK] DataUpdater initialized")
    print()
    
    # Load watchlist
    print("Step 2: Loading watchlist...")
    symbols = updater.load_watchlist()
    print(f"[OK] Loaded {len(symbols)} symbols from watchlist")
    print(f"First 10 symbols: {symbols[:10]}")
    print()
    
    # Test update (incremental)
    print("Step 3: Running incremental update...")
    print("(This will download only new data since last update)")
    print()
    
    try:
        await updater.update_all()
        print()
        print("[OK] Update completed successfully!")
        print()
        
        print("="*80)
        print("[SUCCESS] DATA UPDATE TEST PASSED!")
        print("="*80)
        print()
        print("The 'Update Market Data' button in the dashboard should work now.")
        print()
        
    except Exception as e:
        print()
        print("[ERROR] Update failed!")
        print(f"Error: {e}")
        print()
        
        # Helpful diagnostics
        print("Possible causes:")
        if "api" in str(e).lower() or "key" in str(e).lower():
            print("  - Invalid or missing Polygon.io API key")
            print("  - Check your .env file")
        elif "network" in str(e).lower() or "connection" in str(e).lower():
            print("  - Network connection issue")
            print("  - Check your internet connection")
        elif "rate" in str(e).lower() or "limit" in str(e).lower():
            print("  - API rate limit reached")
            print("  - Wait a few minutes and try again")
        else:
            print("  - Unknown error")
            print("  - Check logs for details")
        
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print()
    print("Testing Data Update Functionality...")
    print()
    
    try:
        asyncio.run(test_data_update())
    except KeyboardInterrupt:
        print()
        print("[CANCELLED] Test cancelled by user")
        sys.exit(1)
