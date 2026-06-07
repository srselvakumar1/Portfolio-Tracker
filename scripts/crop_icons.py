import os
from PIL import Image

grid_path = "/Volumes/SELVA DATA/USER DATA/srselvakumar/.gemini/antigravity/brain/13c90811-4a1a-4239-8963-c2607854fd67/portfolio_pro_icons_set_1777083146926.png"
output_dir = "assets/icons"

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

img = Image.open(grid_path)
width, height = img.size

# 3x3 grid
cell_w = width // 3
cell_h = height // 3

# Define names in order
names = [
    "dashboard.png", "holdings.png", "trade_entry.png",
    "trade_history.png", "tax_report.png", "watchlist.png",
    "valuation.png", "settings.png", "help.png"
]

for i in range(3):
    for j in range(3):
        idx = i * 3 + j
        left = j * cell_w
        top = i * cell_h
        right = (j + 1) * cell_w
        bottom = (i + 1) * cell_h
        
        # Crop and save
        icon = img.crop((left, top, right, bottom))
        icon.save(os.path.join(output_dir, names[idx]))
        print(f"Saved {names[idx]}")
