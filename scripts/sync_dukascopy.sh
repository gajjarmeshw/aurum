#!/bin/bash
# Bulk download XAUUSD data from Dukascopy and sync with Aurum backtest data
# Range: 2024-01-01 to 2026-04-12

PROJECT_ROOT="/Users/mgajjar/Documents/Projects/DEMo/aurum"
DATA_DIR="$PROJECT_ROOT/backtest/data"
DOWNLOAD_DIR="$PROJECT_ROOT/download"

mkdir -p "$DATA_DIR"

TIMEFRAMES=("m5" "m15" "h1" "h4")
AU_TF=("5min" "15min" "1h" "4h")

START_DATE="2024-01-01"
END_DATE="2026-04-12"

for i in "${!TIMEFRAMES[@]}"; do
    TF="${TIMEFRAMES[$i]}"
    AU_FN="XAUUSD_${AU_TF[$i]}.csv"
    
    echo "⬇️ Checking/Downloading XAUUSD $TF ($START_DATE to $END_DATE)..."
    
    # Check if download file already exists in download/ folder
    DOWNLOADED_FILE="$DOWNLOAD_DIR/xauusd-$TF-bid-$START_DATE-$END_DATE.csv"
    
    if [ ! -f "$DOWNLOADED_FILE" ]; then
        npx -y dukascopy-node -i xauusd -from "$START_DATE" -to "$END_DATE" -t "$TF" -f csv
    fi
    
    if [ -f "$DOWNLOADED_FILE" ]; then
        echo "✅ Download found: $DOWNLOADED_FILE"
        echo "🔄 Syncing with $AU_FN..."
        
        python3 -c "
import pandas as pd
import os
try:
    new_df = pd.read_csv('$DOWNLOADED_FILE')
    # Use 'timestamp' if available, otherwise check column 0
    ts_col = 'timestamp' if 'timestamp' in new_df.columns else new_df.columns[0]
    
    new_df['datetime'] = pd.to_datetime(new_df[ts_col], unit='ms')
    new_df = new_df[['datetime', 'open', 'high', 'low', 'close']]

    master_path = '$DATA_DIR/$AU_FN'
    if os.path.exists(master_path):
        old_df = pd.read_csv(master_path)
        old_df['datetime'] = pd.to_datetime(old_df['datetime'])
        final_df = pd.concat([old_df, new_df]).drop_duplicates(subset=['datetime']).sort_values('datetime')
    else:
        final_df = new_df

    final_df.to_csv(master_path, index=False)
    print(f'Done: {master_path} (Bars: {len(final_df)})')
except Exception as e:
    print(f'Error merging $TF: {e}')
"
    else
        echo "❌ No file for $TF at $DOWNLOADED_FILE"
    fi
done

echo "🎉 Synced."
