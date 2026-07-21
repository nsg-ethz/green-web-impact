#!/bin/bash

inkscape noise.jpg \
  --actions="select-all;selection-trace-bitmap;export-filename:noise.svg;export-do" \
  --export-type=svg

