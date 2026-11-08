import cv2
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import math
import os
import json
import copy
import gc

# --- Global Variables for OpenCV Drawing & Viewport ---
drawing = False
mode = 'rectangle'
rois = []
selected_rois_indices = set()
copied_rois = []
current_mouse_pos = (0, 0)
last_lclick_pos = (0, 0) # Tracks last left click for pasting
img_cv = None
finish_requested = False
pending_crop_rect = None 
show_rotation_crosshair = False  # Flag for vertical/horizontal rotation lines

# Sorting state flags
sort_h_reverse = False
sort_v_reverse = False

# History States for Undo/Redo
history_undo = []
history_redo = []

def push_state():
    """Saves the current ROI state to the undo history."""
    global history_undo, history_redo, rois
    history_undo.append(copy.deepcopy(rois))
    history_redo.clear()
    if len(history_undo) > 50: 
        history_undo.pop(0)

# Polygon drawing state
current_polygon = []

# Dragging state variables
is_dragging_rois = False
drag_start_img_pt = (0, 0)
original_rois_state = {}

# UI Layout Constants (Adjusted Pane Widths for Bigger Fonts)
VIEW_W = 950
VIEW_H = 700
LEFT_PANE_W = 280   
RIGHT_PANE_W = 280  
BOTTOM_PANE_H = 70
CANVAS_W = LEFT_PANE_W + VIEW_W + RIGHT_PANE_W
CANVAS_H = VIEW_H + BOTTOM_PANE_H

# Camera / Viewport State
zoom_level = 1.0
pan_x = 0.0
pan_y = 0.0
is_panning = False
pan_start_mouse = (0, 0)
pan_start_offset = (0, 0)

# --- Coordinate Conversion Helpers ---
def screen_to_img(sx, sy):
    ix = (sx - LEFT_PANE_W) / zoom_level + pan_x
    iy = sy / zoom_level + pan_y
    return ix, iy

def img_to_screen(ix, iy):
    sx = (ix - pan_x) * zoom_level + LEFT_PANE_W
    sy = (iy - pan_y) * zoom_level
    return int(sx), int(sy)

def get_roi_center(roi):
    if roi[0] == 'rectangle':
        return ((roi[1] + roi[3]) / 2.0, (roi[2] + roi[4]) / 2.0)
    elif roi[0] == 'circle':
        return (roi[1], roi[2])
    elif roi[0] == 'polygon':
        pts = roi[1]
        if not pts:
            return (0, 0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (0, 0)

def get_composite_canvas(base_img):
    global mode, rois, selected_rois_indices, zoom_level, pan_x, pan_y, current_polygon, pending_crop_rect
    global sort_h_reverse, sort_v_reverse, show_rotation_crosshair
    
    canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
    
    # Draw Background Panels
    canvas[:, :LEFT_PANE_W] = (35, 35, 35)
    canvas[:, LEFT_PANE_W+VIEW_W:] = (35, 35, 35)
    canvas[VIEW_H:, LEFT_PANE_W:LEFT_PANE_W+VIEW_W] = (45, 45, 45) 
    
    img_h, img_w = base_img.shape[:2]
    
    crop_x1, crop_y1 = int(pan_x), int(pan_y)
    crop_x2 = int(pan_x + VIEW_W / zoom_level)
    crop_y2 = int(pan_y + VIEW_H / zoom_level)
    
    v_x1, v_y1 = max(0, crop_x1), max(0, crop_y1)
    v_x2, v_y2 = min(img_w, crop_x2), min(img_h, crop_y2)
    
    if v_x1 < v_x2 and v_y1 < v_y2:
        crop = base_img[v_y1:v_y2, v_x1:v_x2]
        
        dst_x1 = int((v_x1 - crop_x1) * zoom_level)
        dst_y1 = int((v_y1 - crop_y1) * zoom_level)
        dst_w = int((v_x2 - v_x1) * zoom_level)
        dst_h = int((v_y2 - v_y1) * zoom_level)
        
        if dst_w > 0 and dst_h > 0:
            resized = cv2.resize(crop, (dst_w, dst_h))
            canvas[dst_y1:dst_y1+dst_h, LEFT_PANE_W+dst_x1:LEFT_PANE_W+dst_x1+dst_w] = resized

    # --- Draw Rotation Crosshairs (if active) ---
    if show_rotation_crosshair:
        pt1_h = img_to_screen(0, img_h/2)
        pt2_h = img_to_screen(img_w, img_h/2)
        pt1_v = img_to_screen(img_w/2, 0)
        pt2_v = img_to_screen(img_w/2, img_h)
        
        cv2.line(canvas, pt1_h, pt2_h, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.line(canvas, pt1_v, pt2_v, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "PRESS ENTER TO CLEAR CROSSHAIRS", (LEFT_PANE_W + 15, VIEW_H - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    # Draw ROIs
    for i, roi in enumerate(rois):
        is_selected = i in selected_rois_indices
        color = (0, 255, 255) if is_selected else ((0, 255, 0) if roi[0] == 'rectangle' else (255, 0, 0))
        if roi[0] == 'polygon' and not is_selected:
            color = (255, 165, 0) 
        
        if roi[0] == 'rectangle':
            sx1, sy1 = img_to_screen(roi[1], roi[2])
            sx2, sy2 = img_to_screen(roi[3], roi[4])
            cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), color, 2)
            cv2.putText(canvas, str(i+1), (min(sx1, sx2), min(sy1, sy2)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        elif roi[0] == 'circle':
            sx, sy = img_to_screen(roi[1], roi[2])
            sr = int(roi[3] * zoom_level)
            cv2.circle(canvas, (sx, sy), sr, color, 2)
            cv2.putText(canvas, str(i+1), (sx, sy-sr-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        elif roi[0] == 'polygon':
            pts = np.array([img_to_screen(pt[0], pt[1]) for pt in roi[1]], np.int32)
            if len(pts) > 0:
                cv2.polylines(canvas, [pts], isClosed=True, color=color, thickness=2)
                cv2.putText(canvas, str(i+1), (pts[0][0], pts[0][1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    if drawing and hasattr(draw_roi, 'temp_shape') and draw_roi.temp_shape:
        tx, ty = draw_roi.temp_shape
        sx1, sy1 = img_to_screen(draw_roi.ix, draw_roi.iy)
        sx2, sy2 = img_to_screen(tx, ty)
        
        if mode in ['rectangle', 'crop']:
            color = (0, 255, 0) if mode == 'rectangle' else (0, 0, 255)
            cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), color, 2)
            if mode == 'crop':
                cv2.putText(canvas, "CROP", (min(sx1, sx2), min(sy1, sy2)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        elif mode == 'circle':
            sr = int(math.hypot(tx - draw_roi.ix, ty - draw_roi.iy) * zoom_level)
            cv2.circle(canvas, (sx1, sy1), sr, (255, 0, 0), 2)
            
    if mode == 'polygon' and current_polygon:
        pts = np.array([img_to_screen(pt[0], pt[1]) for pt in current_polygon], np.int32)
        if len(pts) > 1:
            cv2.polylines(canvas, [pts], isClosed=False, color=(0, 255, 0), thickness=2)
        cur_sx, cur_sy = img_to_screen(current_mouse_pos[0], current_mouse_pos[1])
        cv2.line(canvas, tuple(pts[-1]), (cur_sx, cur_sy), (0, 255, 0), 2)
        for p in pts:
            cv2.circle(canvas, tuple(p), 4, (0, 0, 255), -1)

    if pending_crop_rect:
        cx1, cy1, cx2, cy2 = pending_crop_rect
        sx1, sy1 = img_to_screen(cx1, cy1)
        sx2, sy2 = img_to_screen(cx2, cy2)
        cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), (0, 165, 255), 2) 
        cv2.putText(canvas, "PRESS ENTER TO CONFIRM CROP", (min(sx1, sx2), min(sy1, sy2)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            
    # --- Bottom Pane Buttons ---
    btn_y1 = VIEW_H + 15
    btn_y2 = VIEW_H + 55
    center_offset = LEFT_PANE_W + (VIEW_W // 2) - 275
    
    bottom_btns = [
        ("Load ROI", center_offset, (70, 70, 150)),
        ("Zoom Out", center_offset + 110, (100, 100, 100)),
        ("Rotate", center_offset + 220, (150, 100, 50)),
        ("Zoom In", center_offset + 330, (100, 100, 100)),
        ("Save ROI", center_offset + 440, (70, 150, 70))
    ]

    for label, bx, bg_col in bottom_btns:
        cv2.rectangle(canvas, (bx, btn_y1), (bx + 100, btn_y2), bg_col, -1)
        cv2.putText(canvas, label, (bx + 8, VIEW_H + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    # --- Left Pane Text & List ---
    cv2.putText(canvas, "Created ROIs:", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(canvas, "(L-Click: Select, R-Click: Delete)", (12, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
    cv2.line(canvas, (5, 60), (LEFT_PANE_W - 5, 60), (255, 255, 255), 1)
    
    for i, roi in enumerate(rois):
        y_pos = 85 + (i * 24)
        if y_pos > CANVAS_H - 20:
            cv2.putText(canvas, "... (more)", (12, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 2)
            break
        text = f"{i+1}: {roi[0][:4]}" 
        if i in selected_rois_indices:
            text += " [S]"
            color = (0, 255, 255)
        else:
            color = (0, 255, 0) if roi[0] == 'rectangle' else ((255, 0, 0) if roi[0] == 'circle' else (255, 165, 0))
        cv2.putText(canvas, text, (12, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # --- Right Pane Buttons & Controls ---
    start_x_right = LEFT_PANE_W + VIEW_W + 10
    cv2.putText(canvas, "TOOLS:", (start_x_right, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.line(canvas, (start_x_right, 40), (CANVAS_W - 10, 40), (255, 255, 255), 1)
    
    # Updated Sorting Labels
    label_h = "Sort (Right/Left)" if sort_h_reverse else "Sort (Left/Right)"
    label_v = "Sort (Bottom/Up)" if sort_v_reverse else "Sort (Up/Down)"
    
    menu_items = [
        ("Rectangle", 'rectangle'),
        ("Circle", 'circle'),
        ("Polygon", 'polygon'),
        ("Crop Image", 'crop'),
        ("Pan Image", 'pan'),
        ("Copy ROIs", 'copy'),
        ("Clear All", 'clear'),
        (label_h, 'sort_h'),
        (label_v, 'sort_v')
    ]
    
    for i, (label, action) in enumerate(menu_items):
        btn_y1 = 50 + (i * 38)
        btn_y2 = btn_y1 + 32
        
        if mode == action:
            cv2.rectangle(canvas, (start_x_right, btn_y1), (CANVAS_W - 10, btn_y2), (0, 220, 220), -1) 
            cv2.putText(canvas, label, (start_x_right + 8, btn_y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
        else:
            color = (50, 50, 200) if action == 'clear' else ((150, 100, 50) if action == 'crop' else ((100, 150, 100) if 'sort' in action else (100, 100, 100)))
            cv2.rectangle(canvas, (start_x_right, btn_y1), (CANVAS_W - 10, btn_y2), color, -1)
            cv2.putText(canvas, label, (start_x_right + 8, btn_y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    text_y = 50 + len(menu_items) * 38 + 15
    controls = [
        "Ctrl+Click: Multi-Sel",
        "Enter: Confirm Crop/Cross",
        "L-Drag (Pan): Move",
        "M-Drag: Pan View",
        "Ctrl+C/X/V: Copy/Cut/Paste",
        "Ctrl+Z: Undo"
    ]
    for i, ctrl in enumerate(controls):
        cv2.putText(canvas, ctrl, (start_x_right, text_y + (i * 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 230), 1)

    # Automatically Perfectly Centered "Process" Button
    rect_x1 = start_x_right
    rect_y1 = CANVAS_H - 65
    rect_x2 = CANVAS_W - 10
    rect_y2 = CANVAS_H - 15
    cv2.rectangle(canvas, (rect_x1, rect_y1), (rect_x2, rect_y2), (0, 160, 0), -1)
    
    text = "Process"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.75
    thick = 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    
    tx = rect_x1 + (rect_x2 - rect_x1 - tw) // 2
    ty = rect_y1 + (rect_y2 - rect_y1 + th) // 2 
    cv2.putText(canvas, text, (tx, ty), font, scale, (255, 255, 255), thick)
        
    return canvas

def draw_roi(event, x, y, flags, param):
    global drawing, mode, img_cv, rois, selected_rois_indices, current_mouse_pos
    global zoom_level, pan_x, pan_y, is_panning, pan_start_mouse, pan_start_offset
    global finish_requested, current_polygon
    global is_dragging_rois, drag_start_img_pt, original_rois_state, copied_rois
    global pending_crop_rect, show_rotation_crosshair
    global sort_h_reverse, sort_v_reverse, last_lclick_pos
    
    if event == cv2.EVENT_LBUTTONDOWN:
        if y >= VIEW_H and LEFT_PANE_W <= x <= LEFT_PANE_W + VIEW_W:
            center_offset = LEFT_PANE_W + (VIEW_W // 2) - 275
            if center_offset <= x <= center_offset + 100:
                fp = filedialog.askopenfilename(title="Load ROIs", filetypes=[("JSON Files", "*.json")])
                if fp:
                    with open(fp, 'r') as f:
                        loaded = json.load(f)
                        push_state()
                        for r in loaded:
                            if r[0] == 'polygon':
                                rois.append((r[0], [tuple(pt) for pt in r[1]]))
                            else:
                                rois.append(tuple(r))
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
            elif center_offset + 110 <= x <= center_offset + 210: 
                zoom_level = max(0.05, zoom_level * 0.8)
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
            elif center_offset + 220 <= x <= center_offset + 320: 
                show_rotation_crosshair = True 
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv)) 
                cv2.waitKey(1) 
                
                angle = simpledialog.askfloat("Rotate Image", "Enter rotation angle in degrees:")
                if angle is not None:
                    h, w = img_cv.shape[:2]
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, angle, 1.0)
                    cos, sin = np.abs(M[0, 0]), np.abs(M[0, 1])
                    nW, nH = int((h * sin) + (w * cos)), int((h * cos) + (w * sin))
                    M[0, 2] += (nW / 2) - center[0]
                    M[1, 2] += (nH / 2) - center[1]
                    img_cv = cv2.warpAffine(img_cv, M, (nW, nH))
                    push_state()
                    rois.clear()
                    selected_rois_indices.clear()
                    current_polygon.clear()
                    pan_x, pan_y = 0, 0
                    zoom_level = min(VIEW_W / nW, VIEW_H / nH)
                
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
            elif center_offset + 330 <= x <= center_offset + 430: 
                zoom_level = min(50.0, zoom_level * 1.25)
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
            elif center_offset + 440 <= x <= center_offset + 540: 
                fp = filedialog.asksaveasfilename(title="Save ROIs", defaultextension=".json", filetypes=[("JSON Files", "*.json")])
                if fp:
                    with open(fp, 'w') as f:
                        json.dump(rois, f)
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return

        start_x_right = LEFT_PANE_W + VIEW_W + 10
        if start_x_right <= x <= CANVAS_W - 10:
            if CANVAS_H - 65 <= y <= CANVAS_H - 15: 
                finish_requested = True
                return
                
            menu_items = ['rectangle', 'circle', 'polygon', 'crop', 'pan', 'copy', 'clear', 'sort_h', 'sort_v']
            for i, action in enumerate(menu_items):
                btn_y1 = 50 + (i * 38)
                btn_y2 = btn_y1 + 32
                if btn_y1 <= y <= btn_y2:
                    if action in ['rectangle', 'circle', 'polygon', 'crop', 'pan']:
                        mode = action
                        if mode != 'crop':
                            pending_crop_rect = None 
                    elif action == 'copy':
                        if selected_rois_indices:
                            copied_rois = [copy.deepcopy(rois[idx]) for idx in selected_rois_indices]
                    elif action == 'clear':
                        push_state()
                        rois.clear()
                        selected_rois_indices.clear()
                        current_polygon.clear()
                    elif action == 'sort_h' or action == 'sort_v':
                        if not selected_rois_indices:
                            indices_to_sort = list(range(len(rois)))
                        else:
                            indices_to_sort = list(selected_rois_indices)
                        
                        if indices_to_sort:
                            push_state()
                            sub_rois = [rois[idx] for idx in indices_to_sort]
                            
                            if action == 'sort_h':
                                sub_rois.sort(key=lambda r: get_roi_center(r)[0], reverse=sort_h_reverse)
                                sort_h_reverse = not sort_h_reverse
                            else:
                                sub_rois.sort(key=lambda r: get_roi_center(r)[1], reverse=sort_v_reverse)
                                sort_v_reverse = not sort_v_reverse
                            
                            indices_to_sort.sort()
                            for dest_idx, sorted_r in zip(indices_to_sort, sub_rois):
                                rois[dest_idx] = sorted_r
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                    return

    is_inside_view = (LEFT_PANE_W <= x < LEFT_PANE_W + VIEW_W) and (0 <= y < VIEW_H)
    is_inside_left_pane = (0 <= x < LEFT_PANE_W)
    
    ix, iy = screen_to_img(x, y)
    current_mouse_pos = (ix, iy)

    if not hasattr(draw_roi, "ix"): draw_roi.ix = -1
    if not hasattr(draw_roi, "iy"): draw_roi.iy = -1
    if not hasattr(draw_roi, "temp_shape"): draw_roi.temp_shape = None
    if not hasattr(draw_roi, "drag_pushed"): draw_roi.drag_pushed = False

    if event == cv2.EVENT_MBUTTONDOWN and is_inside_view:
        is_panning = True
        pan_start_mouse = (x, y)
        pan_start_offset = (pan_x, pan_y)

    elif event == cv2.EVENT_MBUTTONUP:
        is_panning = False

    elif event == cv2.EVENT_LBUTTONDOWN:
        if is_inside_left_pane and y >= 60:
            idx = (y - 85) // 24
            if 0 <= idx < len(rois):
                if flags & cv2.EVENT_FLAG_CTRLKEY:
                    if idx in selected_rois_indices: selected_rois_indices.remove(idx)
                    else: selected_rois_indices.add(idx)
                else:
                    selected_rois_indices.clear()
                    selected_rois_indices.add(idx)
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return

        if is_inside_view:
            last_lclick_pos = (ix, iy)
            
            if mode == 'pan':
                is_panning = True
                pan_start_mouse = (x, y)
                pan_start_offset = (pan_x, pan_y)
                return

            if mode == 'crop':
                pending_crop_rect = None 
                
            if mode == 'polygon' and len(current_polygon) > 0:
                sx0, sy0 = img_to_screen(current_polygon[0][0], current_polygon[0][1])
                dist = math.hypot(x - sx0, y - sy0) 
                if dist < 15: 
                    if len(current_polygon) > 2:
                        push_state()
                        rois.append(('polygon', list(current_polygon)))
                    current_polygon.clear()
                else:
                    current_polygon.append((ix, iy))
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return

            if flags & cv2.EVENT_FLAG_CTRLKEY:
                clicked_roi = -1
                for i in reversed(range(len(rois))):
                    roi = rois[i]
                    if roi[0] == 'rectangle':
                        _, x1, y1, x2, y2 = roi
                        if min(x1, x2) <= ix <= max(x1, x2) and min(y1, y2) <= iy <= max(y1, y2):
                            clicked_roi = i
                            break
                    elif roi[0] == 'circle':
                        _, cx, cy, r = roi
                        if math.hypot(ix - cx, iy - cy) <= r:
                            clicked_roi = i
                            break
                    elif roi[0] == 'polygon':
                        pts_arr = np.array(roi[1], np.float32)
                        if cv2.pointPolygonTest(pts_arr, (ix, iy), False) >= 0:
                            clicked_roi = i
                            break
                
                if clicked_roi != -1:
                    if clicked_roi in selected_rois_indices: selected_rois_indices.remove(clicked_roi)
                    else: selected_rois_indices.add(clicked_roi)
                        
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
            
            clicked_roi = -1
            for i in reversed(range(len(rois))):
                roi = rois[i]
                if roi[0] == 'rectangle':
                    _, x1, y1, x2, y2 = roi
                    if min(x1, x2) <= ix <= max(x1, x2) and min(y1, y2) <= iy <= max(y1, y2):
                        clicked_roi = i
                        break
                elif roi[0] == 'circle':
                    _, cx, cy, r = roi
                    if math.hypot(ix - cx, iy - cy) <= r:
                        clicked_roi = i
                        break
                elif roi[0] == 'polygon':
                    pts_arr = np.array(roi[1], np.float32)
                    if cv2.pointPolygonTest(pts_arr, (ix, iy), False) >= 0:
                        clicked_roi = i
                        break

            if clicked_roi != -1:
                if clicked_roi not in selected_rois_indices:
                    selected_rois_indices.clear()
                    selected_rois_indices.add(clicked_roi)
                    
                is_dragging_rois = True
                drag_start_img_pt = (ix, iy)
                original_rois_state = {idx: copy.deepcopy(rois[idx]) for idx in selected_rois_indices}
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return
                
            selected_rois_indices.clear()
            drawing = True
            draw_roi.ix, draw_roi.iy = ix, iy
            draw_roi.temp_shape = (ix, iy)
            if mode == 'polygon':
                current_polygon.append((ix, iy))
                drawing = False 
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))

    elif event == cv2.EVENT_MOUSEMOVE:
        if is_panning:
            dx = x - pan_start_mouse[0]
            dy = y - pan_start_mouse[1]
            pan_x = pan_start_offset[0] - (dx / zoom_level)
            pan_y = pan_start_offset[1] - (dy / zoom_level)
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
        
        elif is_dragging_rois:
            if not draw_roi.drag_pushed:
                push_state()
                draw_roi.drag_pushed = True

            dx = ix - drag_start_img_pt[0]
            dy = iy - drag_start_img_pt[1]
            
            for idx, r_data in original_rois_state.items():
                if r_data[0] == 'rectangle':
                    rois[idx] = ('rectangle', r_data[1]+dx, r_data[2]+dy, r_data[3]+dx, r_data[4]+dy)
                elif r_data[0] == 'circle':
                    rois[idx] = ('circle', r_data[1]+dx, r_data[2]+dy, r_data[3])
                elif r_data[0] == 'polygon':
                    new_pts = [(p[0]+dx, p[1]+dy) for p in r_data[1]]
                    rois[idx] = ('polygon', new_pts)
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            
        elif drawing or (mode == 'polygon' and len(current_polygon) > 0):
            img_h, img_w = img_cv.shape[:2]
            ix_clipped = max(0, min(ix, img_w - 1))
            iy_clipped = max(0, min(iy, img_h - 1))
            draw_roi.temp_shape = (ix_clipped, iy_clipped)
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))

    elif event == cv2.EVENT_LBUTTONUP:
        if is_panning and mode == 'pan':
            is_panning = False
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            return
            
        if is_dragging_rois:
            is_dragging_rois = False
            original_rois_state.clear()
            draw_roi.drag_pushed = False
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            
        elif drawing:
            drawing = False
            img_h, img_w = img_cv.shape[:2]
            ix_clipped = max(0, min(ix, img_w - 1))
            iy_clipped = max(0, min(iy, img_h - 1))
            
            if mode in ['rectangle', 'crop']:
                if abs(ix_clipped - draw_roi.ix) > 5/zoom_level and abs(iy_clipped - draw_roi.iy) > 5/zoom_level:
                    if mode == 'rectangle':
                        push_state()
                        rois.append(('rectangle', draw_roi.ix, draw_roi.iy, ix_clipped, iy_clipped))
                    elif mode == 'crop':
                        x1, x2 = int(min(draw_roi.ix, ix_clipped)), int(max(draw_roi.ix, ix_clipped))
                        y1, y2 = int(min(draw_roi.iy, iy_clipped)), int(max(draw_roi.iy, iy_clipped))
                        
                        x1 = max(0, x1); y1 = max(0, y1)
                        x2 = min(img_w, x2); y2 = min(img_h, y2)
                        
                        if x2 > x1 and y2 > y1:
                            pending_crop_rect = (x1, y1, x2, y2) 
                            
            elif mode == 'circle':
                radius = math.hypot(ix_clipped - draw_roi.ix, iy_clipped - draw_roi.iy)
                if radius > 2/zoom_level:
                    push_state()
                    rois.append(('circle', draw_roi.ix, draw_roi.iy, radius))
            
            draw_roi.temp_shape = None
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))

    elif event == cv2.EVENT_RBUTTONDOWN:
        if is_inside_view and mode == 'polygon' and len(current_polygon) > 0:
            current_polygon.pop()
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            return

        if is_inside_left_pane and y >= 60:
            idx = (y - 85) // 24
            if 0 <= idx < len(rois):
                push_state()
                rois.pop(idx)
                if idx in selected_rois_indices: selected_rois_indices.remove(idx)
                selected_rois_indices = {i - 1 if i > idx else i for i in selected_rois_indices}
                cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                return

        if is_inside_view:
            for i in reversed(range(len(rois))):
                roi = rois[i]
                hit = False
                if roi[0] == 'rectangle':
                    _, x1, y1, x2, y2 = roi
                    if min(x1, x2) <= ix <= max(x1, x2) and min(y1, y2) <= iy <= max(y1, y2): hit = True
                elif roi[0] == 'circle':
                    _, cx, cy, r = roi
                    if math.hypot(ix - cx, cy - iy) <= r: hit = True
                elif roi[0] == 'polygon':
                    pts_arr = np.array(roi[1], np.float32)
                    if cv2.pointPolygonTest(pts_arr, (ix, iy), False) >= 0: hit = True
                        
                if hit:
                    push_state()
                    rois.pop(i)
                    if i in selected_rois_indices: selected_rois_indices.remove(i)
                    selected_rois_indices = {idx - 1 if idx > i else idx for idx in selected_rois_indices}
                    break
                        
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))


class MasterRGBApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RGB Vegetation Indices Analyzer")
        self.root.geometry("1100x800")

        self.lbl_main = tk.Label(root, text="RGB VEGETATION INDICES ANALYZER", font=("Arial", 20, "bold"), fg="#333")
        self.lbl_main.pack(pady=(10, 0))

        self.indices_def = [
            ("B_G_Ratio", "B / G", "General Ratio Index"),
            ("B_R_Ratio", "B / R", "General Ratio Index"),
            ("BI", "6 * (B / R)", "Zheng et al., 2004"),
            ("R_B_Ratio", "R / B", "General Ratio Index"),
            ("G_R_Ratio", "G / R", "General Ratio Index"),
            ("R_G_Ratio", "R / G", "Gamon & Surfus (1999)"),
            ("G_B_Ratio", "G / B", "General Ratio Index"),
            ("NGRDI", "(G - R) / (G + R)", "Tucker (1979)"),
            ("NDSI_RG", "(R - G) / (R + G)", "General Normalized Ratio"),
            ("NGRR2", "(R + G) / (R - G)", "Modified Ratio Index"),
            ("NDGBI", "(G - B) / (G + B)", "General Normalized Ratio"),
            ("NDSI_BG", "(B - G) / (B + G)", "General Normalized Ratio"),
            ("NPCI", "(R - B) / (R + B)", "Kawashima & Nakatani (1998)"),
            ("ExG", "2*G - R - B", "Woebbecke et al. (1995)"),
            ("ExR", "1.4*R - G", "Meyer et al. (1998)"),
            ("ExB", "1.4*B - G", "Derived Metric"),
            ("ExGExR", "(2*G - R - B) - (1.4*R - G)", "Meyer et al. (1998)"),
            ("CIVE", "0.441*R - 0.811*G + 0.385*B + 18.7875", "Kataoka et al. (2003)"),
            ("GLI", "(2*G - R - B) / (2*G + R + B)", "Louhaichi et al. (2001)"),
            ("VARI", "(G - R) / (G + R - B)", "Gitelson et al. (2002)"),
            ("VEG", "G / ((R^0.667) * (B^0.333))", "Hague et al. (2006)"),
            ("RGVBI", "(G - (B * R)) / (G^2 + (B * R))", "Modified Variant"),
            ("NRI", "R / (R + G + B)", "Perez et al. (2000)"),
            ("NGI", "G / (R + G + B)", "Perez et al. (2000)"),
            ("NBI", "B / (R + G + B)", "Perez et al. (2000)"),
            ("Norm_ExG", "(2*G - R - B) / (R + G + B)", "Normalized Excess Green"),
            ("Norm_ExR", "(1.4*R - G) / (R + G + B)", "Normalized Excess Red"),
            ("GMR", "G - R", "Simple Difference"),
            ("INT", "(R + G + B) / 3", "General Color Space"),
            ("TGI", "-0.5 * (190*(R - G) - 120*(R - B))", "Hunt et al. (2011)"),
            ("MGRVI", "(G^2 - R^2) / (G^2 + R^2)", "Bendig et al. (2015)"),
            ("RGBVI", "(G^2 - R*B) / (G^2 + R*B)", "Bendig et al. (2015)"),
            ("COM", "0.25*ExG + 0.3*ExGR + 0.33*CIVE + 0.12*VEG", "Guerrero et al. (2012)"),
            ("NDI", "128 * (((G - R) / (G + R)) + 1)", "Perez et al. (2000)"),
            ("MExG", "1.262*G - 0.884*R - 0.311*B", "Burgos-Artizzu et al. (2011)"),
            ("RI", "R^2 / (B * G^3)", "Derived Metric"),
            ("HI", "(2*R - G - B) / (G - B)", "Escadafal et al. (1989)"),
            ("CB", "sqrt(R^2 + G^2 + B^2)", "Derived Metric"),
            ("SAT", "(max(RGB) - min(RGB)) / max(RGB)", "Derived Metric"),
            ("Y", "0.299*R + 0.587*G + 0.114*B", "ITU-R BT.601 (1982)"),
            ("Chroma", "sqrt(a*^2 + b*^2)", "CIE (1976)"),
            ("DGCI", "[(H-60)/60 + (1-S) + (1-V)] / 3", "Karcher & Richardson (2003)"),
            ("PSRI_RGB", "(R - B) / G", "Plant Senescence Proxy"),
            ("SR_p", "2*R - G - B", "Senescence Ratio Proxy"),
            ("Yellowness", "(R - G) / R", "Derived Metric"),
            ("LGR", "log(G / R)", "Derived Metric"),
            ("SAVI_RGB", "(1 + 0.5) * (G - R) / (G + R + 0.5)", "Adapted from Huete (1988)"),
            ("OSAVI_RGB", "(G - R) / (G + R + 0.16)", "Adapted from Rondeaux et al. (1996)"),
            ("EVI_RGB", "2.5 * (G - R) / (G + 6*R - 7.5*B + 1)", "Adapted from Huete et al. (2002)"),
            ("GLAI", "25 * ((G - R) / (G + R - B)) + 1.25", "Empirical Leaf Area Proxy"),
            ("SHP", "2 * (R - G - B) / (G - B)", "Structural Shape Index"),
            ("VVI", "(1 - |(R-30)/(R+30)|) * (1 - |(G-50)/(G+50)|) * (1 - |(B-1)/(B+1)|)", "Agapiou et al. (2012)"),
            ("VDVI", "(2*G - R - B) / (2*G + R + B)", "Wang et al. (2015)"), 
            ("WI", "(G - B) / (R - G)", "Woebbecke et al. (1995)"),
            ("CI_R", "(R - B) / R", "Pouget et al. (1990)"),
            ("RDI", "(G - B) / (R - B)", "Ratio Difference Proxy"),
            ("Band_B", "Blue Band Only", "Standard Channel"),
            ("Band_G", "Green Band Only", "Standard Channel"),
            ("Band_R", "Red Band Only", "Standard Channel"),
            ("Hue", "Hue Channel (HIS/HSV)", "Smith (1978)"),
            ("Saturation", "Saturation Channel (HIS/HSV)", "Smith (1978)"),
            ("Intensity_Val", "Value Channel (HIS/HSV)", "Smith (1978)"),
            ("Lightness", "(max + min) / 2", "Smith (1978)"),
            ("CIE_L", "Lightness L* (CIE-Lab)", "CIE (1976)"),
            ("CIE_a", "Green-Red a* (CIE-Lab)", "CIE (1976)"),
            ("CIE_b", "Blue-Yellow b* (CIE-Lab)", "CIE (1976)"),
            ("CIE_Luv_L", "Lightness L* (CIE-Luv)", "CIE (1976)"),
            ("CIE_u", "u* Channel (CIE-Luv)", "CIE (1976)"),
            ("CIE_v", "v* Channel (CIE-Luv)", "CIE (1976)"),
            ("GA", "Green Area (Hue 60-180)", "Casadesús et al. (2007)"),
            ("GGA", "Greener Area (Hue 80-180)", "Casadesús et al. (2007)"),
            ("CSI", "100 * (GA - GGA) / GA", "Vergara-Diaz et al. (2016)"),
            ("NDYI", "(G - B) / (G + B)", "Sulik & Long (2016)"),
            ("IPCA", "(2*G - R - B) / (R + G + B)", "Marchi et al. (2020)"),
            ("I1", "(G - B) / (R + G + B)", "Marchi et al. (2020)"),
            ("I2", "(2*G - R - B) / (R + G + B)", "Marchi et al. (2020)"),
            ("G_Percent", "100 * G / (R + G + B)", "Guijarro et al. (2011)"),
            ("R_Percent", "100 * R / (R + G + B)", "Guijarro et al. (2011)"),
            ("B_Percent", "100 * B / (R + G + B)", "Guijarro et al. (2011)"),
            ("mRVI", "(R^2 - G^2) / (R^2 + G^2)", "Bendig et al. (2015)"),
            ("CIE_X", "X Channel (CIE-XYZ)", "CIE (1931)"),
            ("CIE_Y", "Y Channel (CIE-XYZ)", "CIE (1931)"),
            ("CIE_Z", "Z Channel (CIE-XYZ)", "CIE (1931)"),
            ("YUV_U", "U Channel (YUV Space)", "ITU-R BT.601 (1982)"),
            ("YUV_V", "V Channel (YUV Space)", "ITU-R BT.601 (1982)")
        ]

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill='both', padx=20, pady=10)

        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.tab3 = ttk.Frame(self.notebook)

        self.notebook.add(self.tab1, text='Parameters Selection')
        self.notebook.add(self.tab2, text='Interactive ROI Analysis')
        self.notebook.add(self.tab3, text='Batch Analysis')

        self.setup_tab1()
        self.setup_tab2()
        self.setup_tab3()

    def setup_tab1(self):
        lbl = tk.Label(self.tab1, text="Select the Vegetation Indices and Color Spaces to calculate:", font=("Arial", 12, "bold"))
        lbl.pack(pady=(15,5))

        main_content_frame = tk.Frame(self.tab1)
        main_content_frame.pack(expand=True, fill='both', padx=10, pady=5)

        left_frame = tk.Frame(main_content_frame)
        left_frame.pack(side='left', expand=True, fill='both')

        right_frame = tk.Frame(main_content_frame, width=350)
        right_frame.pack(side='right', fill='y', padx=(20, 0))
        
        try:
            intro_path = None
            for ext in [".png", ".PNG", ".jpg", ".JPG", ".jpeg"]:
                if os.path.exists(f"intro{ext}"):
                    intro_path = f"intro{ext}"
                    break
            if intro_path:
                img_intro = Image.open(intro_path)
                img_intro.thumbnail((320, 400), Image.Resampling.LANCZOS)
                self.intro_photo = ImageTk.PhotoImage(img_intro)
                lbl_intro = tk.Label(right_frame, image=self.intro_photo)
                lbl_intro.pack(pady=5)
            else:
                tk.Label(right_frame, text="[ 'intro' image not found ]", font=("Arial", 10, "italic"), fg="gray").pack(pady=5)
        except Exception as e:
            pass

        try:
            logo_path = None
            for ext in [".png", ".PNG", ".jpg", ".JPG", ".jpeg"]:
                if os.path.exists(f"logo{ext}"):
                    logo_path = f"logo{ext}"
                    break
            if logo_path:
                img_logo = Image.open(logo_path)
                img_logo.thumbnail((320, 150), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(img_logo)
                lbl_logo = tk.Label(right_frame, image=self.logo_photo)
                lbl_logo.pack(pady=5)
            else:
                tk.Label(right_frame, text="[ 'logo' image not found ]", font=("Arial", 10, "italic"), fg="gray").pack(pady=5)
        except Exception as e:
            pass

        creator_text = "Dr. Abdelhalim Khaled\nCrop Ecophysiology\nFaculty of Agronomy\nUniversity of Concepción"
        lbl_creator = tk.Label(right_frame, text=creator_text, font=("Arial", 11, "bold"), fg="#333", justify="center")
        lbl_creator.pack(pady=(5, 10))
        
        btn_frame = tk.Frame(left_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Select All", command=self.select_all_indices, bg="#4CAF50", fg="white", width=15).grid(row=0, column=0, padx=10)
        tk.Button(btn_frame, text="Deselect All", command=self.deselect_all_indices, bg="#f44336", fg="white", width=15).grid(row=0, column=1, padx=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview.Heading", font=("Arial", 11, "bold"), background="#d9d9d9", foreground="black")
        style.configure("Treeview", font=("Arial", 10), rowheight=28)
        style.map('Treeview', background=[('selected', '#4CAF50')], foreground=[('selected', 'white')])

        columns = ("Status", "Index", "Formula", "Citation")
        self.tree = ttk.Treeview(left_frame, columns=columns, show='headings', height=20, style="Treeview")
        self.tree.heading("Status", text="Selected")
        self.tree.heading("Index", text="Parameter Name")
        self.tree.heading("Formula", text="Formula / Description")
        self.tree.heading("Citation", text="Scientific Citation")
        
        self.tree.column("Status", width=80, anchor='center')
        self.tree.column("Index", width=150, anchor='center')
        self.tree.column("Formula", width=250, anchor='w')
        self.tree.column("Citation", width=200, anchor='w')
        self.tree.pack(fill='both', expand=True, pady=10)
        
        self.tree.tag_configure('evenrow', background='#f4f4f4')
        self.tree.tag_configure('oddrow', background='#ffffff')

        for i, (idx, form, cite) in enumerate(self.indices_def):
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", tk.END, values=("[ X ]", idx, form, cite), tags=(tag,))
            
        self.tree.bind('<Double-1>', self.toggle_selection)
        tk.Label(left_frame, text="* Double-click a row to toggle its selection status.", font=("Arial", 10, "italic")).pack(pady=5)

    def toggle_selection(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            vals = list(self.tree.item(item, 'values'))
            vals[0] = "[   ]" if vals[0] == "[ X ]" else "[ X ]"
            self.tree.item(item, values=vals)

    def select_all_indices(self):
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, 'values'))
            vals[0] = "[ X ]"
            self.tree.item(item, values=vals)

    def deselect_all_indices(self):
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, 'values'))
            vals[0] = "[   ]"
            self.tree.item(item, values=vals)

    def get_selected_indices(self):
        return [self.tree.item(item, 'values')[1] for item in self.tree.get_children() if self.tree.item(item, 'values')[0] == "[ X ]"]

    def save_index_images_efficient(self, img_bgr, selected_keys, output_folder, prefix=""):
        """Saves float numpy index arrays as normalized color-mapped images processing one by one to avoid memory crash on large images."""
        os.makedirs(output_folder, exist_ok=True)
        for key in selected_keys:
            self.root.update()  # Keep GUI responsive
            
            # Calculate only ONE index at a time to save memory footprint massively!
            res = self.calculate_rgb_indices_arrays(img_bgr, [key])
            arr = res[key]
            
            arr_min, arr_max = np.nanmin(arr), np.nanmax(arr)
            if arr_max > arr_min:
                norm = ((arr - arr_min) / (arr_max - arr_min) * 255.0).astype(np.uint8)
            else:
                norm = np.zeros_like(arr, dtype=np.uint8)
            
            colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            fname = f"{prefix}{key}.png" if prefix else f"{key}.png"
            cv2.imwrite(os.path.join(output_folder, fname), colored)
            
            # Flush out memory after each parameter image
            del res, arr, norm, colored
            gc.collect()

    def calculate_rgb_indices_arrays(self, img_bgr, selected_keys):
        b = img_bgr[:, :, 0].astype(np.float32)
        g = img_bgr[:, :, 1].astype(np.float32)
        r = img_bgr[:, :, 2].astype(np.float32)

        np.seterr(divide='ignore', invalid='ignore')
        eps = 1e-8
        sum_rgb = r + g + b + eps
        
        exg_arr = 2 * g - r - b
        exr_arr = 1.4 * r - g
        cive_arr = 0.441 * r - 0.811 * g + 0.385 * b + 18.7875
        veg_arr = g / ((r**0.667) * (b**0.333) + eps)

        results = {}
        
        if any(k in selected_keys for k in ["Hue", "Saturation", "Intensity_Val", "GA", "GGA", "CSI", "DGCI"]):
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
            if "Hue" in selected_keys: results["Hue"] = hsv[:,:,0]
            if "Saturation" in selected_keys: results["Saturation"] = hsv[:,:,1]
            if "Intensity_Val" in selected_keys: results["Intensity_Val"] = hsv[:,:,2]
            
            hue_360 = hsv[:,:,0] * 2.0
            if "GA" in selected_keys: results["GA"] = np.where((hue_360 >= 60) & (hue_360 <= 180), 1.0, 0.0)
            if "GGA" in selected_keys: results["GGA"] = np.where((hue_360 >= 80) & (hue_360 <= 180), 1.0, 0.0)
            if "CSI" in selected_keys: 
                ga_mask = (hue_360 >= 60) & (hue_360 <= 180)
                gga_mask = (hue_360 >= 80) & (hue_360 <= 180)
                # Per-pixel map kept only for optional image visualization of the senescent component.
                # True CSI is the regional value 100*(GA - GGA)/GA, computed later from proportions.
                results["CSI"] = np.where(ga_mask, np.where(~gga_mask, 100.0, 0.0), 0.0)
                # Guarantee GA and GGA arrays exist whenever CSI is requested
                if "GA" not in results:
                    results["GA"] = np.where(ga_mask, 1.0, 0.0)
                if "GGA" not in results:
                    results["GGA"] = np.where(gga_mask, 1.0, 0.0)
            if "DGCI" in selected_keys: 
                s_norm = hsv[:,:,1] / 255.0
                v_norm = hsv[:,:,2] / 255.0
                results["DGCI"] = ((hue_360 - 60) / 60.0 + (1.0 - s_norm) + (1.0 - v_norm)) / 3.0
                
            del hsv, hue_360
            gc.collect()

        if any(k in selected_keys for k in ["CIE_L", "CIE_a", "CIE_b", "Chroma"]):
            lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
            if "CIE_L" in selected_keys: results["CIE_L"] = lab[:,:,0]
            if "CIE_a" in selected_keys: results["CIE_a"] = lab[:,:,1]
            if "CIE_b" in selected_keys: results["CIE_b"] = lab[:,:,2]
            if "Chroma" in selected_keys: results["Chroma"] = np.sqrt(lab[:,:,1]**2 + lab[:,:,2]**2)
            
            del lab
            gc.collect()

        if any(k in selected_keys for k in ["CIE_Luv_L", "CIE_u", "CIE_v"]):
            luv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Luv).astype(np.float32)
            if "CIE_Luv_L" in selected_keys: results["CIE_Luv_L"] = luv[:,:,0]
            if "CIE_u" in selected_keys: results["CIE_u"] = luv[:,:,1]
            if "CIE_v" in selected_keys: results["CIE_v"] = luv[:,:,2]
            
            del luv
            gc.collect()

        if any(k in selected_keys for k in ["CIE_X", "CIE_Y", "CIE_Z"]):
            xyz = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2XYZ).astype(np.float32)
            if "CIE_X" in selected_keys: results["CIE_X"] = xyz[:,:,0]
            if "CIE_Y" in selected_keys: results["CIE_Y"] = xyz[:,:,1]
            if "CIE_Z" in selected_keys: results["CIE_Z"] = xyz[:,:,2]
            
            del xyz
            gc.collect()

        if any(k in selected_keys for k in ["YUV_U", "YUV_V"]):
            yuv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YUV).astype(np.float32)
            if "YUV_U" in selected_keys: results["YUV_U"] = yuv[:,:,1]
            if "YUV_V" in selected_keys: results["YUV_V"] = yuv[:,:,2]
            
            del yuv
            gc.collect()

        for key in selected_keys:
            if key == "B_G_Ratio": results[key] = b / (g + eps)
            elif key == "B_R_Ratio": results[key] = b / (r + eps)
            elif key == "BI": results[key] = 6 * (b / (r + eps))
            elif key == "R_B_Ratio": results[key] = r / (b + eps)
            elif key == "G_R_Ratio": results[key] = g / (r + eps)
            elif key == "R_G_Ratio": results[key] = r / (g + eps)
            elif key == "G_B_Ratio": results[key] = g / (b + eps)
            elif key == "NGRDI": results[key] = (g - r) / (g + r + eps)
            elif key == "NDSI_RG": results[key] = (r - g) / (r + g + eps)
            elif key == "NGRR2": results[key] = (r + g) / (r - g + eps)
            elif key == "NDGBI": results[key] = (g - b) / (g + b + eps)
            elif key == "NDSI_BG": results[key] = (b - g) / (b + g + eps)
            elif key == "NPCI": results[key] = (r - b) / (r + b + eps)
            elif key == "ExG": results[key] = exg_arr
            elif key == "ExR": results[key] = exr_arr
            elif key == "ExB": results[key] = 1.4 * b - g
            elif key == "ExGExR": results[key] = exg_arr - exr_arr
            elif key == "CIVE": results[key] = cive_arr
            elif key == "GLI": results[key] = (2 * g - r - b) / (2 * g + r + b + eps)
            elif key == "VARI": results[key] = (g - r) / (g + r - b + eps)
            elif key == "VEG": results[key] = veg_arr
            elif key == "RGVBI": results[key] = (g - (b * r)) / (g**2 + (b * r) + eps)
            elif key == "NRI": results[key] = r / sum_rgb
            elif key == "NGI": results[key] = g / sum_rgb
            elif key == "NBI": results[key] = b / sum_rgb
            elif key == "Norm_ExG": results[key] = exg_arr / sum_rgb
            elif key == "Norm_ExR": results[key] = exr_arr / sum_rgb
            elif key == "GMR": results[key] = g - r
            elif key == "INT": results[key] = sum_rgb / 3.0
            elif key == "TGI": results[key] = -0.5 * (190 * (r - g) - 120 * (r - b))
            elif key == "MGRVI": results[key] = (g**2 - r**2) / (g**2 + r**2 + eps)
            elif key == "RGBVI": results[key] = (g**2 - r * b) / (g**2 + r * b + eps)
            elif key == "COM": results[key] = 0.25*exg_arr + 0.3*(exg_arr - exr_arr) + 0.33*cive_arr + 0.12*veg_arr
            elif key == "NDI": results[key] = 128 * (((g - r) / (g + r + eps)) + 1)
            elif key == "MExG": results[key] = 1.262 * g - 0.884 * r - 0.311 * b
            elif key == "RI": results[key] = r**2 / (b * g**3 + eps)
            elif key == "HI": results[key] = (2 * r - g - b) / (g - b + eps)
            elif key == "CB": results[key] = np.sqrt(r**2 + g**2 + b**2)
            elif key == "SAT": results[key] = (np.max(img_bgr, axis=2) - np.min(img_bgr, axis=2)) / (np.max(img_bgr, axis=2) + eps)
            elif key == "Y": results[key] = 0.299 * r + 0.587 * g + 0.114 * b
            elif key == "PSRI_RGB": results[key] = (r - b) / (g + eps)
            elif key == "SR_p": results[key] = 2 * r - g - b
            elif key == "Yellowness": results[key] = (r - g) / (r + eps)
            elif key == "LGR": results[key] = np.log((g / (r + eps)) + 1e-6)
            
            elif key == "SAVI_RGB": results[key] = (1.5 * (g - r)) / (g + r + 0.5 + eps)
            elif key == "OSAVI_RGB": results[key] = (g - r) / (g + r + 0.16 + eps)
            elif key == "EVI_RGB": results[key] = 2.5 * (g - r) / (g + 6*r - 7.5*b + 1 + eps)
            elif key == "GLAI": results[key] = 25 * ((g - r) / (g + r - b + eps)) + 1.25
            elif key == "SHP": results[key] = 2 * (r - g - b) / (g - b + eps)
            elif key == "VVI": 
                results[key] = (1 - np.abs((r - 30) / (r + 30 + eps))) * \
                               (1 - np.abs((g - 50) / (g + 50 + eps))) * \
                               (1 - np.abs((b - 1) / (b + 1 + eps)))
            elif key == "VDVI": results[key] = (2 * g - r - b) / (2 * g + r + b + eps)
            elif key == "WI": results[key] = (g - b) / (r - g + eps)
            elif key == "CI_R": results[key] = (r - b) / (r + eps)
            elif key == "RDI": results[key] = (g - b) / (r - b + eps)
            
            elif key == "Band_B": results[key] = b
            elif key == "Band_G": results[key] = g
            elif key == "Band_R": results[key] = r
            elif key == "Lightness": results[key] = (np.max(img_bgr, axis=2) + np.min(img_bgr, axis=2)) / 2.0

            elif key == "NDYI": results[key] = (g - b) / (g + b + eps)
            elif key == "IPCA": results[key] = (2 * g - r - b) / sum_rgb
            elif key == "I1": results[key] = (g - b) / sum_rgb
            elif key == "I2": results[key] = (2 * g - r - b) / sum_rgb
            elif key == "G_Percent": results[key] = 100.0 * (g / sum_rgb)
            elif key == "R_Percent": results[key] = 100.0 * (r / sum_rgb)
            elif key == "B_Percent": results[key] = 100.0 * (b / sum_rgb)
            elif key == "mRVI": results[key] = (r**2 - g**2) / (r**2 + g**2 + eps)

        for k in results:
            results[k] = np.nan_to_num(results[k], nan=0.0, posinf=0.0, neginf=0.0)
        return results

    def _extract_roi_means(self, indices_dict, roi_pixels, selected_keys):
        """Extract means. CSI is computed regionally as 100*(GA-GGA)/GA."""
        means = {}
        for k in selected_keys:
            if k == "CSI":
                continue
            vals = indices_dict[k][roi_pixels]
            valid = np.isfinite(vals)
            means[k] = float(np.mean(vals[valid])) if np.any(valid) else 0.0

        if "CSI" in selected_keys:
            ga_arr = indices_dict.get("GA")
            gga_arr = indices_dict.get("GGA")
            if ga_arr is not None and gga_arr is not None:
                ga_vals = ga_arr[roi_pixels]
                gga_vals = gga_arr[roi_pixels]
                ga_valid = np.isfinite(ga_vals)
                gga_valid = np.isfinite(gga_vals)
                ga_mean = float(np.mean(ga_vals[ga_valid])) if np.any(ga_valid) else 0.0
                gga_mean = float(np.mean(gga_vals[gga_valid])) if np.any(gga_valid) else 0.0
                means["CSI"] = 100.0 * (ga_mean - gga_mean) / ga_mean if ga_mean > 0 else 0.0
            else:
                means["CSI"] = 0.0
        return means

    def get_full_image_means(self, img, selected_keys):
        """Chunked full-image means. CSI computed regionally from GA and GGA proportions."""
        h, w = img.shape[:2]
        chunk_size = 2048

        keys_to_compute = list(selected_keys)
        if "CSI" in selected_keys:
            if "GA" not in keys_to_compute:
                keys_to_compute.append("GA")
            if "GGA" not in keys_to_compute:
                keys_to_compute.append("GGA")

        sums = {k: 0.0 for k in keys_to_compute}
        counts = {k: 0 for k in keys_to_compute}

        for y in range(0, h, chunk_size):
            for x in range(0, w, chunk_size):
                self.root.update()
                chunk = img[y:min(y+chunk_size, h), x:min(x+chunk_size, w)]
                res = self.calculate_rgb_indices_arrays(chunk, keys_to_compute)

                for k in keys_to_compute:
                    valid = np.isfinite(res[k])
                    sums[k] += np.sum(res[k][valid])
                    counts[k] += np.sum(valid)

                del res, chunk
                gc.collect()

        means = {}
        for k in selected_keys:
            if k == "CSI":
                ga_mean = (sums["GA"] / counts["GA"]) if counts.get("GA", 0) > 0 else 0.0
                gga_mean = (sums["GGA"] / counts["GGA"]) if counts.get("GGA", 0) > 0 else 0.0
                means["CSI"] = 100.0 * (ga_mean - gga_mean) / ga_mean if ga_mean > 0 else 0.0
            else:
                means[k] = (sums[k] / counts[k]) if counts.get(k, 0) > 0 else 0.0
        return means

    def setup_tab2(self):
        lbl = tk.Label(self.tab2, text="Draw ROIs, calculate selected indices, and save Excel + Images.", font=("Arial", 12))
        lbl.pack(pady=10)
        
        try:
            if os.path.exists("ROIS.JPG"):
                img = Image.open("ROIS.JPG")
                img.thumbnail((700, 450), Image.Resampling.LANCZOS)
                self.rois_photo = ImageTk.PhotoImage(img)
                lbl_img = tk.Label(self.tab2, image=self.rois_photo)
                lbl_img.pack(pady=5)
            else:
                tk.Label(self.tab2, text="[ 'ROIS.JPG' not found ]", font=("Arial", 10, "italic"), fg="gray").pack(pady=5)
        except Exception as e:
            pass

        btn = tk.Button(self.tab2, text="Load RGB Orthomosaic", command=self.run_roi_analysis, font=("Arial", 14), bg="#FF9800", fg="white")
        btn.pack(pady=15)

    def run_roi_analysis(self):
        selected_keys = self.get_selected_indices()
        if not selected_keys:
            return messagebox.showwarning("Warning", "Please select at least one parameter!")

        global img_cv, rois, mode, selected_rois_indices, copied_rois
        global zoom_level, pan_x, pan_y, is_panning, finish_requested
        global is_dragging_rois, current_polygon
        global history_undo, history_redo, pending_crop_rect
        global show_rotation_crosshair, last_lclick_pos
        
        rois = []
        selected_rois_indices = set()
        copied_rois = []
        current_polygon.clear()
        history_undo.clear()
        history_redo.clear()
        mode = 'rectangle'
        finish_requested = False
        is_dragging_rois = False
        pending_crop_rect = None
        show_rotation_crosshair = False

        file_path = filedialog.askopenfilename(title="Select an RGB Image", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff")])
        if not file_path: return

        img_array = np.fromfile(file_path, dtype=np.uint8)
        img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img_cv is None: 
            return messagebox.showerror("Error", "Could not load the image. Ensure the file is not corrupted.")
            
        img_h, img_w = img_cv.shape[:2]
        zoom_level = min(VIEW_W / img_w, VIEW_H / img_h)
        zoom_level = min(1.0, zoom_level)
        
        pan_x = (img_w - (VIEW_W / zoom_level)) / 2
        pan_y = (img_h - (VIEW_H / zoom_level)) / 2
        is_panning = False
        
        cv2.namedWindow('Interactive ROI Selector', cv2.WINDOW_NORMAL)
        cv2.setMouseCallback('Interactive ROI Selector', draw_roi)
        
        cancelled = False

        while True:
            try:
                self.root.update() # Prevent Tkinter from hanging while drawing
                if cv2.getWindowProperty('Interactive ROI Selector', cv2.WND_PROP_VISIBLE) < 1:
                    cancelled = True
                    break
            except:
                cancelled = True
                break
                
            cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            key = cv2.waitKey(10) & 0xFF
            
            if finish_requested:
                break
                
            if key == 13: # Enter Key
                handled = False
                if mode == 'crop' and pending_crop_rect is not None:
                    x1, y1, x2, y2 = pending_crop_rect
                    push_state()
                    img_cv = img_cv[y1:y2, x1:x2]
                    rois.clear()
                    selected_rois_indices.clear()
                    current_polygon.clear()
                    pan_x, pan_y = 0, 0
                    img_h, img_w = img_cv.shape[:2]
                    zoom_level = min(VIEW_W / img_w, VIEW_H / img_h)
                    zoom_level = min(1.0, zoom_level)
                    pending_crop_rect = None
                    handled = True
                    
                if show_rotation_crosshair:
                    show_rotation_crosshair = False
                    handled = True
                
                if handled:
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
                    
            elif key == 3: # Ctrl+C Support
                if selected_rois_indices:
                    copied_rois = [copy.deepcopy(rois[idx]) for idx in selected_rois_indices]
            elif key == 24: # Ctrl+X Support (Cut)
                if selected_rois_indices:
                    copied_rois = [copy.deepcopy(rois[idx]) for idx in selected_rois_indices]
                    push_state()
                    rois = [r for i, r in enumerate(rois) if i not in selected_rois_indices]
                    selected_rois_indices.clear()
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            elif key == 22: # Ctrl+V Support (Paste at last L-click pos)
                if copied_rois:
                    push_state()
                    if len(copied_rois) > 0:
                        cx, cy = get_roi_center(copied_rois[0])
                        dx = last_lclick_pos[0] - cx
                        dy = last_lclick_pos[1] - cy
                    else:
                        dx, dy = 0, 0
                    
                    new_selection = set()
                    start_idx = len(rois)
                    for r in copied_rois:
                        r_copy = copy.deepcopy(r)
                        if r_copy[0] == 'rectangle':
                            r_copy = ('rectangle', r_copy[1]+dx, r_copy[2]+dy, r_copy[3]+dx, r_copy[4]+dy)
                        elif r_copy[0] == 'circle':
                            r_copy = ('circle', r_copy[1]+dx, r_copy[2]+dy, r_copy[3])
                        elif r_copy[0] == 'polygon':
                            r_copy = ('polygon', [(pt[0]+dx, pt[1]+dy) for pt in r_copy[1]])
                        rois.append(r_copy)
                        new_selection.add(start_idx)
                        start_idx += 1
                        
                    selected_rois_indices.clear()
                    selected_rois_indices.update(new_selection)
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            elif key == 26: # Ctrl+Z (Undo) Support Fix
                if history_undo:
                    history_redo.append(copy.deepcopy(rois))
                    rois = history_undo.pop()
                    selected_rois_indices.clear()
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))
            elif key == 25: # Ctrl+Y (Redo) Support Fix
                if history_redo:
                    history_undo.append(copy.deepcopy(rois))
                    rois = history_redo.pop()
                    selected_rois_indices.clear()
                    cv2.imshow('Interactive ROI Selector', get_composite_canvas(img_cv))

        cv2.destroyAllWindows()
        if cancelled or not rois:
            return

        # Show Processing Window to stop GUI hang
        proc_win = tk.Toplevel(self.root)
        proc_win.title("Processing...")
        tk.Label(proc_win, text="Extracting ROIs and computing data...\nLarge images will take some time.", padx=20, pady=20).pack()
        self.root.update()

        try:
            data = []
            img_h, img_w = img_cv.shape[:2]
            
            # --- ROI CROPPING OPTIMIZATION ---
            # To handle Massive Orthomosaics we extract & process bounding boxes ONLY instead of full image
            for i, roi in enumerate(rois):
                self.root.update()
                if roi[0] == 'rectangle':
                    _, x1, y1, x2, y2 = roi
                    x1_i, x2_i = int(min(x1, x2)), int(max(x1, x2))
                    y1_i, y2_i = int(min(y1, y2)), int(max(y1, y2))
                elif roi[0] == 'circle':
                    _, cx, cy, r = roi
                    x1_i, x2_i = int(cx - r), int(cx + r)
                    y1_i, y2_i = int(cy - r), int(cy + r)
                elif roi[0] == 'polygon':
                    pts = np.array(roi[1], dtype=np.int32)
                    x1_i, x2_i = np.min(pts[:, 0]), np.max(pts[:, 0])
                    y1_i, y2_i = np.min(pts[:, 1]), np.max(pts[:, 1])

                # Clamp to image boundaries
                x1_i = max(0, x1_i); y1_i = max(0, y1_i)
                x2_i = min(img_w, x2_i); y2_i = min(img_h, y2_i)

                if x2_i <= x1_i or y2_i <= y1_i:
                    continue # Invalid bounds

                # Crop only the ROI area
                img_crop = img_cv[y1_i:y2_i, x1_i:x2_i]
                
                # Compute only for this small crop (ensure GA/GGA present when CSI requested)
                compute_keys = list(selected_keys)
                if "CSI" in selected_keys:
                    if "GA" not in compute_keys:
                        compute_keys.append("GA")
                    if "GGA" not in compute_keys:
                        compute_keys.append("GGA")
                indices_dict = self.calculate_rgb_indices_arrays(img_crop, compute_keys)

                mask = np.zeros(img_crop.shape[:2], dtype=np.uint8)
                if roi[0] == 'rectangle':
                    cv2.rectangle(mask, (0, 0), (x2_i - x1_i, y2_i - y1_i), 255, -1)
                elif roi[0] == 'circle':
                    cv2.circle(mask, (int(cx - x1_i), int(cy - y1_i)), int(r), 255, -1)
                elif roi[0] == 'polygon':
                    pts_shifted = pts - [x1_i, y1_i]
                    cv2.fillPoly(mask, [pts_shifted], 255)

                roi_pixels = mask > 0
                if not np.any(roi_pixels):
                    continue

                row = {"ROI_ID": i + 1, "Type": roi[0]}
                means = self._extract_roi_means(indices_dict, roi_pixels, selected_keys)
                row.update(means)
                data.append(row)
                
                # Wipe temporary buffers
                del indices_dict, img_crop, mask
                gc.collect()

            df = pd.DataFrame(data)
            
            save_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
            if save_path:
                df.to_excel(save_path, index=False)
                
                if messagebox.askyesno("Save Images", "Would you like to save images of the calculated indices as well?"):
                    img_save_dir = filedialog.askdirectory(title="Select Folder to Save Index Images")
                    if img_save_dir:
                        self.save_index_images_efficient(img_cv, selected_keys, img_save_dir)
                        messagebox.showinfo("Success", f"Excel saved to:\n{save_path}\n\nIndex images saved to:\n{img_save_dir}")
                    else:
                        messagebox.showinfo("Success", f"Data successfully saved to:\n{save_path}")
                else:
                    messagebox.showinfo("Success", f"Data successfully saved to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Processing failed: {str(e)}")
        finally:
            proc_win.destroy()

    def setup_tab3(self):
        lbl = tk.Label(self.tab3, text="Batch Process Multiple Images using Saved ROIs or Full Image", font=("Arial", 12))
        lbl.pack(pady=10)

        btn_batch = tk.Button(self.tab3, text="Run Batch Processing", command=self.run_batch_analysis, font=("Arial", 14), bg="#2196F3", fg="white")
        btn_batch.pack(pady=20)

    def run_batch_analysis(self):
        selected_keys = self.get_selected_indices()
        if not selected_keys:
            return messagebox.showwarning("Warning", "Please select at least one parameter!")

        folder_path = filedialog.askdirectory(title="Select Directory with RGB Images")
        if not folder_path:
            return

        roi_file = filedialog.askopenfilename(title="Select ROI File (.json) [Cancel for Full Image Analysis]", filetypes=[("JSON Files", "*.json")])
        
        loaded_rois = []
        if roi_file:
            with open(roi_file, 'r') as f:
                loaded = json.load(f)
                for r in loaded:
                    if r[0] == 'polygon':
                        loaded_rois.append((r[0], [tuple(pt) for pt in r[1]]))
                    else:
                        loaded_rois.append(tuple(r))

        out_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
        if not out_path:
            return

        save_imgs = messagebox.askyesno("Save Images", "Would you like to save images of calculated indices for each image in the batch?")
        img_out_dir = None
        if save_imgs:
            img_out_dir = filedialog.askdirectory(title="Select Directory to Save Index Images")

        # Show batch processing window to block hanging
        proc_win = tk.Toplevel(self.root)
        proc_win.title("Batch Processing...")
        lbl_status = tk.Label(proc_win, text="Initializing batch processing...", font=("Arial", 11), padx=30, pady=30)
        lbl_status.pack()
        self.root.update()

        try:
            image_extensions = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
            files = [f for f in os.listdir(folder_path) if f.lower().endswith(image_extensions)]

            all_data = []
            for file_name in files:
                lbl_status.config(text=f"Processing File: {file_name}")
                self.root.update()
                
                img_p = os.path.join(folder_path, file_name)
                img_arr = np.fromfile(img_p, dtype=np.uint8)
                img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                img_h, img_w = img.shape[:2]

                if img_out_dir:
                    lbl_status.config(text=f"Saving Index Images for: {file_name}")
                    self.root.update()
                    img_prefix = f"{os.path.splitext(file_name)[0]}_"
                    self.save_index_images_efficient(img, selected_keys, img_out_dir, prefix=img_prefix)

                if loaded_rois:
                    lbl_status.config(text=f"Computing ROIs for: {file_name}")
                    for i, roi in enumerate(loaded_rois):
                        self.root.update()
                        if roi[0] == 'rectangle':
                            _, x1, y1, x2, y2 = roi
                            x1_i, x2_i = int(min(x1, x2)), int(max(x1, x2))
                            y1_i, y2_i = int(min(y1, y2)), int(max(y1, y2))
                        elif roi[0] == 'circle':
                            _, cx, cy, r = roi
                            x1_i, x2_i = int(cx - r), int(cx + r)
                            y1_i, y2_i = int(cy - r), int(cy + r)
                        elif roi[0] == 'polygon':
                            pts = np.array(roi[1], dtype=np.int32)
                            x1_i, x2_i = np.min(pts[:, 0]), np.max(pts[:, 0])
                            y1_i, y2_i = np.min(pts[:, 1]), np.max(pts[:, 1])

                        x1_i = max(0, x1_i); y1_i = max(0, y1_i)
                        x2_i = min(img_w, x2_i); y2_i = min(img_h, y2_i)

                        if x2_i <= x1_i or y2_i <= y1_i:
                            continue

                        img_crop = img[y1_i:y2_i, x1_i:x2_i]
                        # Ensure GA/GGA present when CSI requested
                        compute_keys = list(selected_keys)
                        if "CSI" in selected_keys:
                            if "GA" not in compute_keys:
                                compute_keys.append("GA")
                            if "GGA" not in compute_keys:
                                compute_keys.append("GGA")
                        indices_dict = self.calculate_rgb_indices_arrays(img_crop, compute_keys)

                        mask = np.zeros(img_crop.shape[:2], dtype=np.uint8)
                        if roi[0] == 'rectangle':
                            cv2.rectangle(mask, (0, 0), (x2_i - x1_i, y2_i - y1_i), 255, -1)
                        elif roi[0] == 'circle':
                            cv2.circle(mask, (int(cx - x1_i), int(cy - y1_i)), int(r), 255, -1)
                        elif roi[0] == 'polygon':
                            pts_shifted = pts - [x1_i, y1_i]
                            cv2.fillPoly(mask, [pts_shifted], 255)

                        roi_pixels = mask > 0
                        if not np.any(roi_pixels):
                            continue

                        row = {"Image": file_name, "ROI_ID": i + 1, "Type": roi[0]}
                        means = self._extract_roi_means(indices_dict, roi_pixels, selected_keys)
                        row.update(means)
                        all_data.append(row)
                        
                        del indices_dict, img_crop, mask
                        gc.collect()
                else:
                    # Full image processing dynamically handles big orthomosaics block-by-block
                    lbl_status.config(text=f"Computing Full Image means for: {file_name}")
                    self.root.update()
                    means = self.get_full_image_means(img, selected_keys)
                    
                    row = {"Image": file_name, "ROI_ID": "Full Image", "Type": "Whole"}
                    for k in selected_keys:
                        # ONLY Mean, parameter name isolated.
                        row[k] = means[k]
                    all_data.append(row)
                    
                del img, img_arr
                gc.collect()

            df = pd.DataFrame(all_data)
            df.to_excel(out_path, index=False)
            messagebox.showinfo("Batch Complete", f"Batch analysis completed! Saved to:\n{out_path}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Batch Processing failed: {str(e)}")
        finally:
            proc_win.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MasterRGBApp(root)
    root.mainloop()