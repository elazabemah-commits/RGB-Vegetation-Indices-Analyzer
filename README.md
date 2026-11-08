# RGB Vegetation Indices Analyzer

A comprehensive, interactive desktop application for calculating a wide range of **RGB-based vegetation indices** and color metrics from digital images and orthomosaics.

Developed by **Dr. Abdelhalim Khaled Elazab**  
akhaled@udec.cl
Crop Ecophysiology  
Faculty of Agronomy  
University of Concepción
Chile

## Features

- **Interactive ROI Selection**: Draw rectangles, circles, and polygons on images. Supports pan, zoom, multi-select, drag-to-move, copy/cut/paste, undo/redo, sorting, cropping, and image rotation.
- **Extensive Index Library**: Calculates 80+ vegetation indices, ratios, normalized indices, and color space transformations (HSV, CIE Lab, Luv, XYZ, YUV, etc.), including:
  - Classic indices: ExG, ExR, GLI, VARI, NGRDI, RGBVI, MGRVI, CIVE, TGI, and many more
  - Color channels and percentages
  - Advanced metrics: DGCI, CSI, GLAI, SAVI_RGB, EVI_RGB, etc.
- **Memory-Efficient Processing**: Optimized for large orthomosaics by processing ROI bounding boxes and using chunked computation for full-image analysis.
- **Batch Processing**: Analyze multiple images using saved ROI files or full-image means.
- **Export Options**:
  - Excel (.xlsx) with mean values per ROI
  - Color-mapped PNG images for each selected index
- **User-Friendly GUI**: Built with Tkinter + OpenCV for a responsive interactive experience.

## Installation

1. Ensure you have **Python 3.8+** installed.
2. Clone this repository:
   ```bash
   git clone https://github.com/elazabemah-commits/RGB-Vegetation-Indices-Analyzer.git
   cd RGB-Vegetation-Indices-Analyzer
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   
or

1. Ensure you have **Python 3.8+** installed.

2. Install
```bash
pyinstaller --onefile --windowed RGBAnalyzer.py
```

## Usage

Run the application:

```bash
python RGBAnalyzer.py
```

### Workflow

1. **Parameters Selection** tab: Choose which vegetation indices to calculate (double-click to toggle).
2. **Interactive ROI Analysis** tab:
   - Click **Load RGB Orthomosaic**
   - Draw ROIs using the tools on the right
   - Click **Process** to compute means and export to Excel
   - Optionally save index visualization images
3. **Batch Analysis** tab:
   - Select a folder of images
   - Optionally load a previously saved ROI JSON file (or analyze full images)
   - Export results to Excel

### ROI File Format

ROIs are saved/loaded as JSON files containing lists of rectangles, circles, or polygons.

## Supported Image Formats

PNG, JPG, JPEG, BMP, TIF, TIFF (including large orthomosaics)

## Optional Assets

The application looks for the following optional images in the working directory to display in the GUI:
- `intro.png` / `intro.jpg` — introductory image
- `logo.png` / `logo.jpg` — logo
- `ROIS.JPG` — example ROI image

## Requirements

See `requirements.txt`:
- opencv-python
- numpy
- pandas
- Pillow
- openpyxl

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Citation

If you use this tool in your research, please cite appropriately and acknowledge the developer:

> Elazab, A. (2026). RGB Vegetation Indices Analyzer [Computer software]. University of Concepción. https://github.com/elazabemah-commits/RGB-Vegetation-Indices-Analyzer.

---

*For questions or contributions, please open an issue or pull request.*
