#!/bin/bash
# Bulk download XAUUSD data from Dukascopy and sync with Aurum backtest data
# Range: 2024-01-01 to 2026-04-12

DATA_DIR="/Users/mgajjar/Documents/Projects/DEMo/aurum/backtest/data"
mkdir -p "$DATA_DIR"

TIMEFRAMES=("m5" "m15" "h1" "h4")
AU_TF=("5min" "15min" "1h" "4h")

START_DATE="2024-01-01"
END_DATE="2026-04-12"

for i in "${!TIMEFRAMES[@]}"; do
    TF="${TIMEFRAMES[$i]}"
    AU_FN="XAUUSD_${AU_TF[$i]}.csv"
    
    echo "⬇️ Downloading XAUUSD $TF ($START_DATE to $END_DATE)..."
    
    # Run dukascopy-node (assuming npx is installed)
    # npx xauusd-m15-bid-2024-01-01-2026-04-12.csv will be created
    npx -y dukascopy-node -i xauusd -from "$START_DATE" -to "$END_DATE" -t "$TF" -f csv
    
    # Find the newly created file (usually in current dir)
    DOWNLOADED_FILE=$(ls xauusd-$TF-bid-*.csv | head -n 1)
    
    if [ -f "$DOWNLOADED_FILE" ]; then
        echo "✅ Download complete: $DOWNLOADED_FILE"
        echo "🔄 Syncing with $AU_FN..."
        
        # Simple Python bridge to merge and format correctly
        python3 -c "
import pandas as pd
new_df = pd.read_csv('$DOWNLOADED_FILE')
# Dukascopy format: 'timestamp', 'open', 'high', 'low', 'close', 'volume'
# Aurum format: 'datetime', 'open', 'high', 'low', 'close'
new_df['datetime'] = pd.to_datetime(new_df['timestamp'], unit='ms')
new_df = new_df[['datetime', 'open', 'high', 'low', 'close']]

master_path = '$DATA_DIR/$AU_FN'
if pd.io.common.file_exists(master_path):
    old_df = pd.read_csv(master_path)
    old_df['datetime'] = pd.to_datetime(old_df['datetime'])
    final_df = pd.concat([old_df, new_df]).drop_duplicates(subset=['datetime']).sort_values('datetime')
else:
    final_df = new_df

final_df.to_csv(master_path, index=False)
print(f'Successfully merged into {master_path}. Total bars: {len(final_df)}')
"
        rm "$DOWNLOADED_FILE"
    else
        echo "❌ Failed to download $TF"
    fi
done

echo "🎉 Bulk download and sync complete."
