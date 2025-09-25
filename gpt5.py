# pentagon_ball.py
# 说明：
# - 一个红色小球在一个顺时针旋转的正五边形内部弹跳
# - 小球受重力影响
# - 碰撞检测为圆-线段（closest point）检测
# - 碰撞响应考虑旋转边的线速度（v_wall = omega x r），并用恢复系数 restitution
# - 按键：Space 暂停/继续, R 重置, ↑/↓ 增/减 角速度, ←/→ 增/减 恢复系数

import pygame
import sys
import math
import numpy as np
from dataclasses import dataclass

# ------------------- 配置 -------------------
WIDTH, HEIGHT = 1000, 700
FPS = 120

PENTAGON_CENTER = np.array([WIDTH // 2, HEIGHT // 2], dtype=float)
PENTAGON_RADIUS = 250.0
PENTAGON_SIDES = 5

GRAVITY = 1400.0  # px/s^2
BALL_RADIUS = 14.0
BALL_MASS = 1.0

# 默认顺时针缓慢旋转 => omega 取负（rad/s）。用户可按键修改
DEFAULT_OMEGA_DEG = -12.0  # deg/s (负值代表顺时针)
DEFAULT_RESTITUTION = 0.85  # 恢复系数

# 可视
BG_COLOR = (6, 17, 34)
POLY_COLOR = (30, 140, 200, 80)
POLY_EDGE_COLOR = (150, 200, 230)
BALL_COLOR = (200, 40, 40)
INFO_COLOR = (220, 220, 220)

# --------------------------------------------

@dataclass
class Ball:
    pos: np.ndarray
    vel: np.ndarray
    r: float = BALL_RADIUS
    m: float = BALL_MASS

    def integrate(self, dt):
        # 速度受重力影响，y 向下为正
        self.vel[1] += GRAVITY * dt
        self.pos += self.vel * dt

    def draw(self, surf):
        pygame.draw.circle(surf, BALL_COLOR, self.pos.astype(int), int(self.r))


def polygon_vertices(center, radius, sides, angle_offset=-math.pi/2.0):
    """返回以原点为中心的正多边形基准顶点（相对原点）"""
    pts = []
    for i in range(sides):
        a = angle_offset + i * 2.0 * math.pi / sides
        pts.append(np.array([math.cos(a) * radius, math.sin(a) * radius], dtype=float))
    return pts


def rotated_polygon(center, radius, sides, theta):
    """返回世界坐标下的多边形顶点（每个点为 np.array([x,y])），并且带有 local coords"""
    base = polygon_vertices(np.zeros(2), radius, sides)
    pts = []
    c, s = math.cos(theta), math.sin(theta)
    for p in base:
        rx = c * p[0] - s * p[1]
        ry = s * p[0] + c * p[1]
        world = np.array([center[0] + rx, center[1] + ry], dtype=float)
        local = np.array([rx, ry], dtype=float)  # 相对中心的局部坐标，用于计算墙线速度
        pts.append((world, local))
    return pts


def closest_point_on_segment(p, a, b):
    """返回线段 AB 上到点 P 的最近点，以及参数 t(0..1)"""
    ab = b - a
    ab2 = ab.dot(ab)
    if ab2 == 0:
        return a.copy(), 0.0
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab2))
    return a + ab * t, t


def wall_velocity_at(local_r, omega):
    """2D 叉乘：omega × r => v = (-omega * r.y, omega * r.x)
       omega in rad/s, local_r in px (relative to polygon center)"""
    return np.array([-omega * local_r[1], omega * local_r[0]], dtype=float)


def resolve_circle_segment_collision(ball: Ball, p1_world, p2_world, p1_local, p2_local, omega, restitution):
    """
    p1_world/p2_world: segment endpoints in world coords
    p1_local/p2_local: their local coords relative to center (for wall velocity interpolation)
    """
    closest, t = closest_point_on_segment(ball.pos, p1_world, p2_world)
    diff = ball.pos - closest
    dist = np.linalg.norm(diff)
    if dist >= ball.r:
        return False  # 没碰撞

    # 法线（从墙指向球）
    if dist == 0:
        # 避免零向量：设定一个小法线
        n = np.array([0.0, -1.0], dtype=float)
    else:
        n = diff / dist

    # 插值计算接触点的 local 坐标（用于计算墙在接触点处的线速度）
    local_closest = p1_local + (p2_local - p1_local) * t
    v_wall = wall_velocity_at(local_closest, omega)

    # 相对速度
    rel_v = ball.vel - v_wall
    vn = np.dot(rel_v, n)

    # 只有当相对速度沿法线指向墙（vn < 0）时作反弹；否则只做位置分离修正（避免粘连）
    if vn < 0:
        # 使法线分量变为 -e * vn，等价于 newRelV = rel_v - (1+e)*vn*n
        new_rel_v = rel_v - (1.0 + restitution) * vn * n
        # 可选加入简单的切向摩擦：微弱衰减切向速度（模拟摩擦）
        tangent = np.array([-n[1], n[0]])
        vt = np.dot(new_rel_v, tangent)
        vt *= 0.99  # 0.99 为摩擦系数（可调）
        new_rel_v = new_rel_v - np.dot(new_rel_v, tangent) * tangent + vt * tangent

        ball.vel = new_rel_v + v_wall
    else:
        # 如果没有明显朝墙的速度，也可能是嵌入状态 -> 减缓切向速度
        tangent = np.array([-n[1], n[0]])
        vt = np.dot(rel_v, tangent)
        vt *= 0.98
        new_rel_v = rel_v - np.dot(rel_v, tangent) * tangent + vt * tangent
        ball.vel = new_rel_v + v_wall

    # 位置修正：将球推到墙外
    penetration = ball.r - dist
    if penetration > 0:
        # 用一点额外的缓冲，把球沿法线推进到外面
        ball.pos += n * (penetration + 1e-3)

    return True


def draw_polygon(surface, pts_world):
    # 填充与描边
    poly = [tuple(p[0]) for p in pts_world]
    # fill with semi-transparent polygon: pygame 没有直接带alpha的形状填充，使用临时 surface
    tmp = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pygame.draw.polygon(tmp, (20, 70, 110, 80), poly)
    surface.blit(tmp, (0, 0))
    pygame.draw.polygon(surface, POLY_EDGE_COLOR, poly, width=2)


def reset_ball():
    # 将球放在多边形中心上方的一点并给一个初速度
    pos = PENTAGON_CENTER + np.array([0.0, -PENTAGON_RADIUS * 0.35], dtype=float)
    vel = np.array([260.0, -120.0], dtype=float)
    return Ball(pos=pos, vel=vel)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("红色小球在顺时针旋转的五边形内弹跳（Python / pygame）")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 16)

    ball = reset_ball()
    theta = 0.0
    omega = math.radians(DEFAULT_OMEGA_DEG)  # rad/s
    restitution = DEFAULT_RESTITUTION

    paused = False

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0  # 秒
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    paused = not paused
                elif ev.key == pygame.K_r:
                    ball = reset_ball()
                    theta = 0.0
                elif ev.key == pygame.K_UP:
                    # 增加顺时针速度的绝对值（omega 负方向更大），这里让用户更直观：
                    # 如果 omega 目前为负（顺时针），再按 UP 则数值更负（更快顺时针）
                    if omega <= 0:
                        omega -= math.radians(6.0)
                    else:
                        omega += math.radians(6.0)
                elif ev.key == pygame.K_DOWN:
                    # 减小顺时针速度
                    if omega <= 0:
                        omega += math.radians(6.0)
                    else:
                        omega -= math.radians(6.0)
                elif ev.key == pygame.K_LEFT:
                    restitution = max(0.0, restitution - 0.02)
                elif ev.key == pygame.K_RIGHT:
                    restitution = min(1.0, restitution + 0.02)

        if not paused:
            # integrate
            ball.integrate(dt)
            theta += omega * dt

            # polygon world and local vertices
            poly = rotated_polygon(PENTAGON_CENTER, PENTAGON_RADIUS, PENTAGON_SIDES, theta)

            # 对每条边进行碰撞检测与响应
            for i in range(len(poly)):
                p1_world, p1_local = poly[i]
                p2_world, p2_local = poly[(i + 1) % len(poly)]
                resolve_circle_segment_collision(ball, p1_world, p2_world, p1_local, p2_local, omega, restitution)

            # 防止球飞出过远（数值爆炸时的保护）
            dist_center = np.linalg.norm(ball.pos - PENTAGON_CENTER)
            if dist_center > PENTAGON_RADIUS * 3.0:
                ball = reset_ball()

            # 可选限制最大速度
            vmax = 4000.0
            vmag = np.linalg.norm(ball.vel)
            if vmag > vmax:
                ball.vel *= (vmax / vmag)

        # --- 绘制 ---
        screen.fill(BG_COLOR)

        # 背景微光效果
        grad = pygame.Surface((WIDTH, HEIGHT))
        grad.fill((0, 0, 0))
        screen.blit(grad, (0, 0))

        # 多边形
        poly = rotated_polygon(PENTAGON_CENTER, PENTAGON_RADIUS, PENTAGON_SIDES, theta)
        draw_polygon(screen, poly)

        # 画球
        ball.draw(screen)

        # 绘制信息
        info_lines = [
            f"Space: 暂停/继续    R: 重置    ↑/↓: 调整角速度    ←/→: 调整恢复系数",
            f"omega (deg/s): {math.degrees(omega):+.2f}    restitution: {restitution:.3f}",
            f"ball pos: ({ball.pos[0]:.1f}, {ball.pos[1]:.1f}) vel: ({ball.vel[0]:.1f}, {ball.vel[1]:.1f})"
        ]
        y = 8
        for line in info_lines:
            surf = font.render(line, True, INFO_COLOR)
            screen.blit(surf, (10, y))
            y += 20

        pygame.display.flip()

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
