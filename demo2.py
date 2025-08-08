import pygame
import random
import sys

# 初始化pygame
pygame.init()

# 游戏常量
WIDTH, HEIGHT = 800, 600
PLAYER_SIZE = 50
OBSTACLE_SIZE = 30
PLAYER_SPEED = 8
OBSTACLE_SPEED = 5
OBSTACLE_SPAWN_RATE = 15 # 数值越小，生成越快

# 颜色定义
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
BLACK = (0, 0, 0)

# 创建游戏窗口
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("躲避障碍物")

# 时钟，控制游戏速度
clock = pygame.time.Clock()


# 玩家类
class Player:
    def __init__(self):
        self.x = WIDTH // 2 - PLAYER_SIZE // 2
        self.y = HEIGHT - PLAYER_SIZE - 10
        self.width = PLAYER_SIZE
        self.height = PLAYER_SIZE
        self.speed = PLAYER_SPEED

    def draw(self):
        pygame.draw.rect(screen, BLUE, (self.x, self.y, self.width, self.height))

    def move(self, direction):
        if direction == "left" and self.x > 0:
            self.x -= self.speed
        if direction == "right" and self.x < WIDTH - self.width:
            self.x += self.speed


# 障碍物类
class Obstacle:
    def __init__(self):
        self.x = random.randint(0, WIDTH - OBSTACLE_SIZE)
        self.y = -OBSTACLE_SIZE
        self.width = OBSTACLE_SIZE
        self.height = OBSTACLE_SIZE
        self.speed = OBSTACLE_SPEED

    def draw(self):
        pygame.draw.rect(screen, RED, (self.x, self.y, self.width, self.height))

    def fall(self):
        self.y += self.speed
        return self.y < HEIGHT  # 如果超出屏幕返回False

    def check_collision(self, player):
        # 简单的碰撞检测
        if (self.x < player.x + player.width and
                self.x + self.width > player.x and
                self.y < player.y + player.height and
                self.y + self.height > player.y):
            return True
        return False


# 游戏主函数
def game_loop():
    global OBSTACLE_SPEED, OBSTACLE_SPAWN_RATE
    player = Player()
    obstacles = []
    score = 0
    spawn_counter = 0

    running = True
    while running:
        # 处理事件
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # 键盘控制
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            player.move("left")
        if keys[pygame.K_RIGHT]:
            player.move("right")

        # 清屏
        screen.fill(WHITE)

        # 生成障碍物
        spawn_counter += 1
        if spawn_counter >= OBSTACLE_SPAWN_RATE:
            obstacles.append(Obstacle())
            spawn_counter = 0
            # 随着分数增加，提高难度
            if score % 10 == 0 and score > 0:
                OBSTACLE_SPEED = min(OBSTACLE_SPEED + 0.2, 15)
                OBSTACLE_SPAWN_RATE = max(OBSTACLE_SPAWN_RATE - 2, 10)

        # 处理障碍物
        for obstacle in obstacles[:]:
            if not obstacle.fall():
                obstacles.remove(obstacle)
                score += 1
            else:
                obstacle.draw()
                if obstacle.check_collision(player):
                    print(f"游戏结束！你的分数是: {score}")
                    running = False

        # 绘制玩家
        player.draw()

        # 显示分数
        font = pygame.font.Font(None, 36)
        score_text = font.render(f"分数: {score}", True, BLACK)
        screen.blit(score_text, (10, 10))

        # 更新屏幕
        pygame.display.flip()

        # 控制帧率
        clock.tick(60)

    pygame.quit()
    sys.exit()


# 启动游戏
if __name__ == "__main__":
    game_loop()