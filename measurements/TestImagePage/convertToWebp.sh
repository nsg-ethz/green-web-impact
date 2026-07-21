#!/bin/bash


find . -type f \( -iname "*.jpg" -o -iname "*.png" \) | while read -r f; do
  out="${f%.*}.webp"
  magick "$f" -auto-orient -strip -quality 80 "$out"
done
