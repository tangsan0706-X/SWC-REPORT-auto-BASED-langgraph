"""纯 Python 几何工具库 — 无 scipy/shapely 依赖。

从 cad_feature_analyzer.py 搬迁的基础几何函数 + PlacementEngine 所需的新算法。

函数列表:
  基础:
    dist, polyline_length, shoelace_area, polygon_centroid, points_bounds
  凸包/凹包:
    convex_hull, knn_concave_hull
  碰撞/交叉:
    line_segment_intersection, point_in_polygon, aabb_overlap, polygons_overlap
  裁剪:
    clip_polygon (Sutherland-Hodgman), clip_polyline (Cohen-Sutherland)
  偏移/缩放:
    offset_polyline, scale_polygon
  采样/提取:
    sample_points_in_polygon, polygon_edges, longest_edge, edges_facing
  地形:
    find_lowest_point, slope_direction_vector
  辅助:
    nearest_point_on_polyline, merge_close_points
"""

from __future__ import annotations

import math
from typing import List, Tuple, Optional

# 类型别名
Point = Tuple[float, float]
Polygon = List[Point]
Polyline = List[Point]
AABB = Tuple[float, float, float, float]  # (x_min, y_min, x_max, y_max)


# ═══════════════════════════════════════════════════════════════
# 基础
# ═══════════════════════════════════════════════════════════════

def dist(a: Point, b: Point) -> float:
    """两点欧几里得距离。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def polyline_length(pts: Polyline) -> float:
    """折线总长度。"""
    total = 0.0
    for i in range(len(pts) - 1):
        total += math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
    return total


def shoelace_area(pts: Polygon) -> float:
    """Shoelace 公式计算多边形面积 (返回绝对值)。"""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


def _signed_area(pts: Polygon) -> float:
    """Shoelace 有符号面积 (正=逆时针, 负=顺时针)。"""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0


def polygon_centroid(pts: Polygon) -> Point:
    """多边形质心 (基于 Shoelace)。"""
    n = len(pts)
    if n == 0:
        return (0.0, 0.0)
    if n <= 2:
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        return (cx, cy)
    area = 0.0
    cx, cy = 0.0, 0.0
    for i in range(n):
        j = (i + 1) % n
        cross = pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        area += cross
        cx += (pts[i][0] + pts[j][0]) * cross
        cy += (pts[i][1] + pts[j][1]) * cross
    area /= 2.0
    if abs(area) < 1e-10:
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        return (cx, cy)
    cx /= (6.0 * area)
    cy /= (6.0 * area)
    return (cx, cy)


def points_bounds(pts: List[Point]) -> AABB:
    """点列表的 AABB 边界。"""
    if not pts:
        return (0, 0, 0, 0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# ═══════════════════════════════════════════════════════════════
# 凸包 / 凹包
# ═══════════════════════════════════════════════════════════════

def convex_hull(points: List[Point]) -> Polygon:
    """Graham scan 凸包算法。"""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def knn_concave_hull(
    points: List[Point], k: int = 5,
) -> Polygon:
    """KNN 凹包算法 (Moreira & Santos 2007 简化版)。

    从最左点出发，每步找 k 个最近邻，选最大左转角的邻居。
    无 scipy/shapely 依赖，O(n·k·log n)。
    k 不足或闭合失败时回退到 convex_hull()。
    """
    pts = list(set(points))
    n = len(pts)
    if n < 3:
        return convex_hull(pts)
    if n <= k:
        return convex_hull(pts)

    # 起始点: 最左下角
    start_idx = 0
    for i in range(1, n):
        if pts[i][0] < pts[start_idx][0] or (
            pts[i][0] == pts[start_idx][0] and pts[i][1] < pts[start_idx][1]
        ):
            start_idx = i

    hull = [pts[start_idx]]
    used = {start_idx}
    current = start_idx
    prev_angle = 0.0

    max_steps = n * 2
    for _step in range(max_steps):
        dists = []
        for i, p in enumerate(pts):
            if i == current:
                continue
            if i in used and not (i == start_idx and len(hull) > 2):
                continue
            d = dist(pts[current], p)
            dists.append((d, i))

        if not dists:
            break

        dists.sort(key=lambda x: x[0])
        neighbors = [idx for _, idx in dists[:k]]

        best_idx = neighbors[0]
        best_angle = -float("inf")
        for ni in neighbors:
            angle = math.atan2(
                pts[ni][1] - pts[current][1],
                pts[ni][0] - pts[current][0],
            )
            turn = angle - prev_angle
            while turn <= -math.pi:
                turn += 2 * math.pi
            while turn > math.pi:
                turn -= 2 * math.pi
            if turn > best_angle:
                best_angle = turn
                best_idx = ni

        prev_angle = math.atan2(
            pts[best_idx][1] - pts[current][1],
            pts[best_idx][0] - pts[current][0],
        )
        current = best_idx

        if current == start_idx and len(hull) > 2:
            break

        hull.append(pts[current])
        used.add(current)

    if len(hull) < 3:
        return convex_hull(points)

    hull_area = shoelace_area(hull)
    convex_area = shoelace_area(convex_hull(points))
    if convex_area > 0 and hull_area / convex_area < 0.3:
        return convex_hull(points)

    return hull


# ═══════════════════════════════════════════════════════════════
# 碰撞 / 交叉
# ═══════════════════════════════════════════════════════════════

def line_segment_intersection(
    p1: Point, p2: Point, p3: Point, p4: Point,
) -> Optional[Point]:
    """两线段交点 (None=不相交)。"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        return (ix, iy)
    return None


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """射线法判断点在多边形内。"""
    x, y = point
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def aabb_overlap(a: AABB, b: AABB) -> bool:
    """AABB 碰撞快筛。"""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def polygons_overlap(a: Polygon, b: Polygon) -> bool:
    """精确多边形碰撞检测 (AABB 快筛 + 边交叉 + 包含检测)。"""
    if len(a) < 3 or len(b) < 3:
        return False

    # Level 1: AABB 快筛
    ba = points_bounds(a)
    bb = points_bounds(b)
    if not aabb_overlap(ba, bb):
        return False

    # Level 2: 边-边交叉检测
    na, nb = len(a), len(b)
    for i in range(na):
        ni = (i + 1) % na
        for j in range(nb):
            nj = (j + 1) % nb
            if line_segment_intersection(a[i], a[ni], b[j], b[nj]) is not None:
                return True

    # Level 3: 包含检测 (A 完全在 B 内，或 B 完全在 A 内)
    if point_in_polygon(a[0], b):
        return True
    if point_in_polygon(b[0], a):
        return True

    return False


# ═══════════════════════════════════════════════════════════════
# 裁剪
# ═══════════════════════════════════════════════════════════════

def clip_polygon(subject: Polygon, clip: Polygon) -> Polygon:
    """Sutherland-Hodgman 多边形裁剪。

    裁剪 subject 多边形到 clip 多边形内部。
    clip 多边形假定为逆时针顺序 (或任意凸多边形)。
    """
    if len(subject) < 3 or len(clip) < 3:
        return []

    def _inside(p: Point, edge_start: Point, edge_end: Point) -> bool:
        """点在裁剪边左侧 (内侧)。"""
        return ((edge_end[0] - edge_start[0]) * (p[1] - edge_start[1]) -
                (edge_end[1] - edge_start[1]) * (p[0] - edge_start[0])) >= 0

    def _intersect(p1: Point, p2: Point, edge_start: Point, edge_end: Point) -> Point:
        """线段与裁剪边的交点。"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = edge_start
        x4, y4 = edge_end
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p1  # 平行，返回 p1 避免除零
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    output = list(subject)
    n_clip = len(clip)

    for i in range(n_clip):
        if not output:
            return []
        edge_start = clip[i]
        edge_end = clip[(i + 1) % n_clip]
        input_list = list(output)
        output = []

        for j in range(len(input_list)):
            current = input_list[j]
            prev = input_list[j - 1]
            curr_inside = _inside(current, edge_start, edge_end)
            prev_inside = _inside(prev, edge_start, edge_end)

            if curr_inside:
                if not prev_inside:
                    output.append(_intersect(prev, current, edge_start, edge_end))
                output.append(current)
            elif prev_inside:
                output.append(_intersect(prev, current, edge_start, edge_end))

    return output


def clip_polyline(line: Polyline, bounds: AABB) -> List[Polyline]:
    """Cohen-Sutherland 折线裁剪到 AABB 内。

    返回裁剪后的多段折线列表 (折线可能被 AABB 切断为多段)。
    """
    x_min, y_min, x_max, y_max = bounds

    INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8

    def _code(x: float, y: float) -> int:
        code = INSIDE
        if x < x_min:
            code |= LEFT
        elif x > x_max:
            code |= RIGHT
        if y < y_min:
            code |= BOTTOM
        elif y > y_max:
            code |= TOP
        return code

    def _clip_segment(x0, y0, x1, y1):
        """Cohen-Sutherland 单线段裁剪。返回裁剪后线段或 None。"""
        c0, c1 = _code(x0, y0), _code(x1, y1)
        for _ in range(20):
            if not (c0 | c1):
                return (x0, y0, x1, y1)
            if c0 & c1:
                return None
            c = c0 if c0 else c1
            if c & TOP:
                x = x0 + (x1 - x0) * (y_max - y0) / (y1 - y0) if abs(y1 - y0) > 1e-12 else x0
                y = y_max
            elif c & BOTTOM:
                x = x0 + (x1 - x0) * (y_min - y0) / (y1 - y0) if abs(y1 - y0) > 1e-12 else x0
                y = y_min
            elif c & RIGHT:
                y = y0 + (y1 - y0) * (x_max - x0) / (x1 - x0) if abs(x1 - x0) > 1e-12 else y0
                x = x_max
            elif c & LEFT:
                y = y0 + (y1 - y0) * (x_min - x0) / (x1 - x0) if abs(x1 - x0) > 1e-12 else y0
                x = x_min
            else:
                break
            if c == c0:
                x0, y0, c0 = x, y, _code(x, y)
            else:
                x1, y1, c1 = x, y, _code(x, y)
        return None

    result: List[Polyline] = []
    current_segment: Polyline = []

    for i in range(len(line) - 1):
        seg = _clip_segment(line[i][0], line[i][1], line[i + 1][0], line[i + 1][1])
        if seg is not None:
            x0, y0, x1, y1 = seg
            if current_segment:
                # 检查是否与上一段连续
                last = current_segment[-1]
                if abs(last[0] - x0) < 1e-6 and abs(last[1] - y0) < 1e-6:
                    current_segment.append((x1, y1))
                else:
                    result.append(current_segment)
                    current_segment = [(x0, y0), (x1, y1)]
            else:
                current_segment = [(x0, y0), (x1, y1)]
        else:
            if current_segment:
                result.append(current_segment)
                current_segment = []

    if current_segment:
        result.append(current_segment)

    return result


# ═══════════════════════════════════════════════════════════════
# 偏移 / 缩放
# ═══════════════════════════════════════════════════════════════

def offset_polyline(pts: Polyline, distance: float, side: str = "left") -> Polyline:
    """折线法向偏移 (排水沟沿边坡布置用)。

    沿折线每段的法向方向偏移指定距离。
    side: "left" = 行进方向左侧, "right" = 行进方向右侧。
    """
    if len(pts) < 2 or abs(distance) < 1e-12:
        return list(pts)

    sign = 1.0 if side == "left" else -1.0
    result: Polyline = []

    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-12:
            continue
        # 法向 (行进方向左侧: 旋转90°逆时针)
        nx = -dy / seg_len * sign * distance
        ny = dx / seg_len * sign * distance

        p0 = (pts[i][0] + nx, pts[i][1] + ny)
        p1 = (pts[i + 1][0] + nx, pts[i + 1][1] + ny)

        if not result:
            result.append(p0)
            result.append(p1)
        else:
            # 取上一段终点和当前段起点的中点作为平滑过渡
            last = result[-1]
            mid = ((last[0] + p0[0]) / 2, (last[1] + p0[1]) / 2)
            result[-1] = mid
            result.append(p1)

    return result


def scale_polygon(pts: Polygon, factor: float) -> Polygon:
    """多边形从质心缩放。"""
    if len(pts) < 3:
        return list(pts)
    cx, cy = polygon_centroid(pts)
    return [(cx + (p[0] - cx) * factor, cy + (p[1] - cy) * factor) for p in pts]


# ═══════════════════════════════════════════════════════════════
# 采样 / 提取
# ═══════════════════════════════════════════════════════════════

def sample_points_in_polygon(polygon: Polygon, spacing: float) -> List[Point]:
    """多边形内均匀采样点。

    在 AABB 内按 spacing 网格采样，过滤出在多边形内部的点。
    """
    if len(polygon) < 3 or spacing <= 0:
        return []

    bbox = points_bounds(polygon)
    x_min, y_min, x_max, y_max = bbox
    points: List[Point] = []

    y = y_min + spacing / 2
    while y < y_max:
        x = x_min + spacing / 2
        while x < x_max:
            if point_in_polygon((x, y), polygon):
                points.append((x, y))
            x += spacing
        y += spacing

    return points


def polygon_edges(pts: Polygon) -> List[Tuple[Point, Point]]:
    """提取多边形所有边 (闭合)。"""
    if len(pts) < 2:
        return []
    edges = []
    n = len(pts)
    for i in range(n):
        edges.append((pts[i], pts[(i + 1) % n]))
    return edges


def longest_edge(pts: Polygon) -> Tuple[Point, Point]:
    """返回多边形最长边的两个端点。"""
    edges = polygon_edges(pts)
    if not edges:
        return (pts[0], pts[0]) if pts else ((0, 0), (0, 0))
    return max(edges, key=lambda e: dist(e[0], e[1]))


def edges_facing(pts: Polygon, direction: str) -> List[Tuple[Point, Point]]:
    """返回多边形面朝特定方向的边。

    direction: "N", "S", "E", "W", "NE", "NW", "SE", "SW"
    通过边的法向量与目标方向的点积筛选。
    """
    dir_map = {
        "N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0),
        "NE": (0.707, 0.707), "NW": (-0.707, 0.707),
        "SE": (0.707, -0.707), "SW": (-0.707, -0.707),
    }
    target = dir_map.get(direction.upper(), (0, 1))
    result = []

    edges = polygon_edges(pts)
    for p1, p2 in edges:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-12:
            continue
        # 外法向 (假定逆时针多边形: 法向向外 = 顺时针旋转90°)
        nx = dy / seg_len
        ny = -dx / seg_len
        # 点积
        dot = nx * target[0] + ny * target[1]
        if dot > 0.3:  # 允许一定偏差
            result.append((p1, p2))

    return result


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def nearest_point_on_polyline(point: Point, polyline: Polyline) -> Point:
    """点到折线最近点。"""
    best_pt = polyline[0] if polyline else point
    best_d = float("inf")
    for i in range(len(polyline) - 1):
        ax, ay = polyline[i]
        bx, by = polyline[i + 1]
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-12:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / seg_len_sq))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(point[0] - px, point[1] - py)
        if d < best_d:
            best_d = d
            best_pt = (px, py)
    return best_pt


def merge_close_points(points: List[Point], threshold: float) -> List[Point]:
    """合并距离小于 threshold 的临近点 (取均值)。"""
    if not points:
        return []
    merged = []
    used = [False] * len(points)
    for i, p in enumerate(points):
        if used[i]:
            continue
        cluster = [p]
        used[i] = True
        for j in range(i + 1, len(points)):
            if used[j]:
                continue
            if math.hypot(points[j][0] - p[0], points[j][1] - p[1]) < threshold:
                cluster.append(points[j])
                used[j] = True
        cx = sum(pt[0] for pt in cluster) / len(cluster)
        cy = sum(pt[1] for pt in cluster) / len(cluster)
        merged.append((cx, cy))
    return merged


def find_lowest_point(
    elevation_points: List[Tuple[float, float, float]],
    within_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[Tuple[float, float]]:
    """找标高最低的点 (用于沉沙池选址)。可限制在 bbox 范围内。"""
    pts = elevation_points
    if within_bbox:
        x0, y0, x1, y1 = within_bbox
        pts = [(x, y, z) for x, y, z in pts
               if x0 <= x <= x1 and y0 <= y <= y1]
    if not pts:
        return None
    lowest = min(pts, key=lambda p: p[2])
    return (lowest[0], lowest[1])


def slope_direction_vector(direction_str: str) -> Optional[Tuple[float, float]]:
    """将方位描述 ("NW→SE", "SE" 等) 转为单位向量 (dx, dy)。
    返回下坡方向 (水流方向) 的单位向量。"""
    parts = direction_str.replace("->", "→").split("→")
    target = parts[-1].strip().upper()

    _DIR_MAP = {
        "N": (0.0, 1.0), "S": (0.0, -1.0), "E": (1.0, 0.0), "W": (-1.0, 0.0),
        "NE": (0.707, 0.707), "NW": (-0.707, 0.707),
        "SE": (0.707, -0.707), "SW": (-0.707, -0.707),
    }
    return _DIR_MAP.get(target)


def sample_along_polyline(pts: Polyline, spacing: float) -> List[Point]:
    """沿折线按固定间距均匀采样。"""
    if not pts or spacing <= 0:
        return []
    total = polyline_length(pts)
    if total < spacing:
        return [pts[0]] if pts else []

    samples = [pts[0]]
    accum = 0.0
    for i in range(len(pts) - 1):
        seg_len = dist(pts[i], pts[i + 1])
        if seg_len < 1e-12:
            continue
        accum += seg_len
        while accum >= spacing:
            accum -= spacing
            t = 1.0 - accum / seg_len if seg_len > 0 else 0.5
            t = max(0.0, min(1.0, t))
            sx = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
            sy = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
            samples.append((sx, sy))

    return samples


def polygon_subtract_obstacles(polygon: Polygon, obstacles: List[Polygon],
                                shrink_factor: float = 0.85) -> Polygon:
    """从多边形中简化减去障碍物: 缩放后检测是否重叠。

    简化策略: 缩小多边形到 shrink_factor，避开障碍物。
    不做精确布尔运算 (需 shapely)，而是通过缩放逼近。
    """
    result = scale_polygon(polygon, shrink_factor)
    # 验证: 如果缩放后仍与任何障碍物重叠，进一步缩小
    for _ in range(3):
        overlaps = any(polygons_overlap(result, obs) for obs in obstacles if len(obs) >= 3)
        if not overlaps:
            break
        result = scale_polygon(result, 0.9)
    return result


# ═══════════════════════════════════════════════════════════════
# v2 新增工具函数 (PlacementEngine v2 所需)
# ═══════════════════════════════════════════════════════════════

def buffer_point(center: Point, radius: float, n_segments: int = 16) -> Polygon:
    """将点缓冲为圆形多边形 (n_segments 个顶点)。"""
    cx, cy = center
    pts = []
    for i in range(n_segments):
        angle = 2.0 * math.pi * i / n_segments
        px = cx + radius * math.cos(angle)
        py = cy + radius * math.sin(angle)
        pts.append((px, py))
    return pts


def create_rectangle_at(
    center: Point, width: float, height: float, angle_deg: float = 0.0,
) -> Polygon:
    """在指定位置创建矩形 (可旋转)。

    Args:
        center: 矩形中心点
        width, height: 宽度和高度
        angle_deg: 旋转角度 (度, 逆时针)
    """
    hw, hh = width / 2, height / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]

    if abs(angle_deg) > 1e-6:
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        corners = [(x * cos_a - y * sin_a, x * sin_a + y * cos_a)
                   for x, y in corners]

    cx, cy = center
    return [(cx + x, cy + y) for x, y in corners]


def polyline_trim(pts: Polyline, start_ratio: float, end_ratio: float) -> Polyline:
    """裁剪折线到指定比例范围 [start_ratio, end_ratio]。

    Args:
        pts: 折线点序列
        start_ratio: 起始位置比例 (0.0~1.0)
        end_ratio: 结束位置比例 (0.0~1.0)

    Returns:
        裁剪后的折线
    """
    if len(pts) < 2 or start_ratio >= end_ratio:
        return list(pts)

    total = polyline_length(pts)
    if total < 1e-12:
        return list(pts)

    start_dist = total * max(0.0, min(1.0, start_ratio))
    end_dist = total * max(0.0, min(1.0, end_ratio))

    result: Polyline = []
    accum = 0.0

    for i in range(len(pts) - 1):
        seg_len = dist(pts[i], pts[i + 1])
        next_accum = accum + seg_len

        if next_accum >= start_dist and not result:
            # 插入起始点
            if seg_len > 1e-12:
                t = (start_dist - accum) / seg_len
                sx = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
                sy = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
                result.append((sx, sy))
            else:
                result.append(pts[i])

        if result and accum <= end_dist:
            if next_accum <= end_dist:
                result.append(pts[i + 1])
            else:
                # 插入结束点
                if seg_len > 1e-12:
                    t = (end_dist - accum) / seg_len
                    ex = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
                    ey = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
                    result.append((ex, ey))
                break

        accum = next_accum

    return result if len(result) >= 2 else list(pts)


def buffer_polygon(pts: Polygon, distance: float) -> Polygon:
    """多边形法向外扩/内缩 (正值外扩, 负值内缩)。

    沿每条边的外法向偏移指定距离, 计算相邻偏移线的交点。
    简单实现, 适用于凸多边形和近凸多边形。
    """
    if len(pts) < 3 or abs(distance) < 1e-12:
        return list(pts)

    n = len(pts)
    # 确保逆时针方向 (正面积 = 逆时针)
    area = _signed_area(pts)
    ordered = list(pts) if area > 0 else list(reversed(pts))
    if distance < 0:
        # 内缩 = 反转方向后外扩
        ordered = list(reversed(ordered))
        distance = -distance

    # 计算每条边的外法向偏移线 (两个端点)
    offset_lines = []
    for i in range(n):
        p0 = ordered[i]
        p1 = ordered[(i + 1) % n]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-12:
            offset_lines.append((p0, p1))
            continue
        # 外法向 (逆时针多边形: 左侧 = 外侧)
        nx = -dy / seg_len * distance
        ny = dx / seg_len * distance
        offset_lines.append(
            ((p0[0] + nx, p0[1] + ny), (p1[0] + nx, p1[1] + ny))
        )

    # 相邻偏移线求交点
    result = []
    for i in range(n):
        a0, a1 = offset_lines[i]
        b0, b1 = offset_lines[(i + 1) % n]
        inter = _line_line_intersection(a0, a1, b0, b1)
        if inter:
            result.append(inter)
        else:
            result.append(a1)

    return result


def _line_line_intersection(
    a0: Point, a1: Point, b0: Point, b1: Point,
) -> Optional[Point]:
    """两条直线 (非线段) 的交点。返回 None 表示平行。"""
    d1x = a1[0] - a0[0]
    d1y = a1[1] - a0[1]
    d2x = b1[0] - b0[0]
    d2y = b1[1] - b0[1]
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-12:
        return None
    t = ((b0[0] - a0[0]) * d2y - (b0[1] - a0[1]) * d2x) / denom
    return (a0[0] + t * d1x, a0[1] + t * d1y)
