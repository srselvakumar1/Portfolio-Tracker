#!/bin/bash

# Create iconset directory
mkdir -p assets/app_icon.iconset

# Source image
SRC="assets/app_icon.png"

# Resize into different versions
sips -s format png -z 16 16     "$SRC" --out assets/app_icon.iconset/icon_16x16.png
sips -s format png -z 32 32     "$SRC" --out assets/app_icon.iconset/icon_16x16@2x.png
sips -s format png -z 32 32     "$SRC" --out assets/app_icon.iconset/icon_32x32.png
sips -s format png -z 64 64     "$SRC" --out assets/app_icon.iconset/icon_32x32@2x.png
sips -s format png -z 128 128   "$SRC" --out assets/app_icon.iconset/icon_128x128.png
sips -s format png -z 256 256   "$SRC" --out assets/app_icon.iconset/icon_128x128@2x.png
sips -s format png -z 256 256   "$SRC" --out assets/app_icon.iconset/icon_256x256.png
sips -s format png -z 512 512   "$SRC" --out assets/app_icon.iconset/icon_256x256@2x.png
sips -s format png -z 512 512   "$SRC" --out assets/app_icon.iconset/icon_512x512.png
sips -s format png -z 1024 1024 "$SRC" --out assets/app_icon.iconset/icon_512x512@2x.png

# Create icns file
iconutil -c icns assets/app_icon.iconset -o assets/app_icon.icns

echo "Generated assets/app_icon.icns"
