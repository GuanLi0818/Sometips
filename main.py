import sys
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QSlider, QPushButton, QSizePolicy)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
import mediapipe as mp


class HandGestureRecognizer:
    """手势识别核心类（基于MediaPipe）"""

    def __init__(self):
        # 初始化MediaPipe手势检测器
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils  # 用于绘制手部关键点
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,  # 非静态图片模式（实时视频）
            max_num_hands=1,  # 最多检测1只手
            min_detection_confidence=0.7,  # 检测置信度阈值
            min_tracking_confidence=0.5  # 跟踪置信度阈值
        )

        # 手势映射：根据手指弯曲状态定义常见手势
        self.GESTURE_MAP = {
            "00000": "石头（握拳）",
            "11111": "布（张开手）",
            "01100": "剪刀（食指+中指伸出）",
            "10000": "点赞（拇指伸出）",
            "11001": "OK（拇指+食指圈住）"
        }

    def get_finger_status(self, hand_landmarks, image_width, image_height):
        """
        判断每根手指的弯曲状态（0=弯曲，1=伸直）
        返回值：5位字符串（拇指、食指、中指、无名指、小指）
        """
        finger_status = []

        # 1. 拇指判断（特殊：需结合x坐标，避免左右手方向影响）
        thumb_tip = hand_landmarks.landmark[self.mp_hands.HandLandmark.THUMB_TIP]
        thumb_ip = hand_landmarks.landmark[self.mp_hands.HandLandmark.THUMB_IP]
        # 拇指伸直条件：指尖x坐标 > 指节x坐标（右手）或 指尖x坐标 < 指节x坐标（左手）
        if (thumb_tip.x > thumb_ip.x and image_width / 2 < thumb_tip.x) or \
                (thumb_tip.x < thumb_ip.x and image_width / 2 > thumb_tip.x):
            finger_status.append("1")
        else:
            finger_status.append("0")

        # 2. 食指-小指判断（通用：指尖y坐标 < 第三指节y坐标即伸直）
        for finger_tip_idx in [
            self.mp_hands.HandLandmark.INDEX_FINGER_TIP,
            self.mp_hands.HandLandmark.MIDDLE_FINGER_TIP,
            self.mp_hands.HandLandmark.RING_FINGER_TIP,
            self.mp_hands.HandLandmark.PINKY_TIP
        ]:
            finger_tip = hand_landmarks.landmark[finger_tip_idx]
            finger_pip = hand_landmarks.landmark[finger_tip_idx - 2]  # 第三指节（PIP）
            if finger_tip.y < finger_pip.y:
                finger_status.append("1")
            else:
                finger_status.append("0")

        return "".join(finger_status)

    def recognize_gesture(self, frame):
        """
        处理单帧画面，返回手势结果和绘制关键点后的画面
        frame: OpenCV格式的画面（BGR）
        返回：(gesture_name, annotated_frame)
        """
        # 转换颜色空间（OpenCV默认BGR，MediaPipe需要RGB）
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image_height, image_width, _ = frame.shape
        gesture_name = "未识别手势"

        # 处理帧并检测手势
        results = self.hands.process(rgb_frame)
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                # 1. 绘制手部关键点和连接线
                self.mp_drawing.draw_landmarks(
                    frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS,
                    self.mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                    self.mp_drawing.DrawingSpec(color=(255, 0, 0), thickness=2)
                )

                # 2. 判断手指状态并识别手势
                finger_status = self.get_finger_status(hand_landmarks, image_width, image_height)
                gesture_name = self.GESTURE_MAP.get(finger_status, f"未知（{finger_status}）")

        return gesture_name, frame

    def release(self):
        """释放资源"""
        self.hands.close()


class CameraThread(QThread):
    """摄像头采集与手势识别线程（避免阻塞UI）"""
    # 信号：传递处理后的画面和手势结果
    frame_signal = pyqtSignal(np.ndarray, str)
    # 信号：传递摄像头是否打开成功
    camera_status_signal = pyqtSignal(bool)

    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index  # 摄像头索引（默认0=内置摄像头）
        self.is_running = False  # 线程运行状态
        self.cap = None  # OpenCV摄像头对象
        self.recognizer = HandGestureRecognizer()  # 手势识别器
        self.confidence = 0.7  # 识别置信度（可通过UI调节）

    def set_camera_index(self, index):
        """切换摄像头索引"""
        self.camera_index = index
        if self.cap is not None:
            self.cap.release()
            self.cap = cv2.VideoCapture(self.camera_index)

    def set_confidence(self, confidence):
        """更新识别置信度"""
        self.confidence = confidence
        self.recognizer.hands.min_detection_confidence = confidence

    def run(self):
        """线程主逻辑：读取摄像头→识别手势→发送信号"""
        self.is_running = True
        self.cap = cv2.VideoCapture(self.camera_index)

        # 检查摄像头是否打开成功
        if not self.cap.isOpened():
            self.camera_status_signal.emit(False)
            self.is_running = False
            return
        self.camera_status_signal.emit(True)

        # 循环读取帧
        while self.is_running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                break  # 读取失败则退出

            # 镜像翻转画面（更符合用户操作习惯）
            frame = cv2.flip(frame, 1)

            # 手势识别
            gesture_name, annotated_frame = self.recognizer.recognize_gesture(frame)

            # 发送画面和手势结果到UI线程
            self.frame_signal.emit(annotated_frame, gesture_name)

            # 控制帧率（避免CPU占用过高）
            QThread.msleep(30)  # 约33帧/秒

    def stop(self):
        """停止线程并释放资源"""
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
        self.recognizer.release()
        self.wait()  # 等待线程退出


class GestureRecognitionWindow(QMainWindow):
    """主窗口类（UI界面）"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时手势识别（PyQt5+MediaPipe）")
        self.setGeometry(100, 100, 800, 600)  # 窗口位置和大小
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # 初始化UI组件
        self.init_ui()

        # 初始化摄像头线程
        self.camera_thread = CameraThread(camera_index=0)
        self.camera_thread.frame_signal.connect(self.update_frame)
        self.camera_thread.camera_status_signal.connect(self.update_camera_status)

    def init_ui(self):
        """构建UI布局（修复预览框变大问题）"""
        # 1. 主布局（垂直布局）
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 2. 摄像头预览区域（核心修改：固定尺寸+禁止拉伸）
        self.preview_label = QLabel()
        # 固定预览框尺寸（如 640x480，符合常见摄像头分辨率）
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setMaximumSize(640, 480)
        # 禁止预览框自动调整尺寸（避免随画面拉伸）
        self.preview_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.preview_label.setStyleSheet("border: 2px solid #333; background-color: #000;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.preview_label, stretch=0)  # 取消拉伸权重（stretch=0）

        # 3. 手势结果显示区域（不变）
        self.result_label = QLabel("手势结果：未识别")
        self.result_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50;")
        self.result_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.result_label, stretch=0)

        # 4. 控制区域（水平布局：不变）
        control_layout = QHBoxLayout()

        self.camera_btn = QPushButton("切换摄像头（当前：内置）")
        self.camera_btn.clicked.connect(self.switch_camera)
        control_layout.addWidget(self.camera_btn)

        self.confidence_slider = QSlider(Qt.Horizontal)
        self.confidence_slider.setRange(50, 90)
        self.confidence_slider.setValue(70)
        self.confidence_slider.setToolTip("识别置信度（越高越严格）")
        self.confidence_slider.valueChanged.connect(self.update_confidence)
        control_layout.addWidget(QLabel("置信度："))
        control_layout.addWidget(self.confidence_slider)
        self.confidence_label = QLabel("70%")
        control_layout.addWidget(self.confidence_label)

        self.start_stop_btn = QPushButton("开始识别")
        self.start_stop_btn.clicked.connect(self.toggle_camera)
        control_layout.addWidget(self.start_stop_btn)

        main_layout.addLayout(control_layout, stretch=0)

        # 5. 固定主窗口尺寸（防止窗口整体变大）
        self.setFixedSize(700, 650)  # 宽度700（预览框640+左右边距20*2），高度650（预览框480+其他区域）
        # 禁止窗口最大化（可选，进一步防止拉伸）
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMaximizeButtonHint)

    def update_frame(self, frame, gesture_name):
        """更新摄像头预览画面和手势结果"""
        # 1. 转换OpenCV帧为PyQt可用的QPixmap
        image_height, image_width, channel = frame.shape
        bytes_per_line = channel * image_width
        # OpenCV是BGR格式，需转换为RGB
        q_image = QImage(frame.data, image_width, image_height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_image)

        # 2. 缩放画面以适应预览区域（保持比例）
        scaled_pixmap = pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled_pixmap)

        # 3. 更新手势结果
        self.result_label.setText(f"手势结果：{gesture_name}")

    def update_camera_status(self, is_success):
        """更新摄像头状态提示"""
        if not is_success:
            self.preview_label.setText("摄像头打开失败！\n请检查摄像头是否连接或被占用")
            self.start_stop_btn.setText("开始识别")

    def toggle_camera(self):
        """启停摄像头识别"""
        if not self.camera_thread.is_running:
            # 开始识别
            self.camera_thread.start()
            self.start_stop_btn.setText("停止识别")
            self.preview_label.setText("正在启动摄像头...")
        else:
            # 停止识别
            self.camera_thread.stop()
            self.start_stop_btn.setText("开始识别")
            self.preview_label.setText("摄像头已停止\n点击「开始识别」重新启动")

    def switch_camera(self):
        """切换摄像头（内置→外接，或外接→内置）"""
        current_index = self.camera_thread.camera_index
        new_index = 1 if current_index == 0 else 0
        self.camera_thread.set_camera_index(new_index)

        # 更新按钮文本
        btn_text = "切换摄像头（当前：外接）" if new_index == 1 else "切换摄像头（当前：内置）"
        self.camera_btn.setText(btn_text)

        # 若摄像头正在运行，重启以应用新索引
        if self.camera_thread.is_running:
            self.camera_thread.stop()
            self.camera_thread.start()
            self.preview_label.setText("正在切换摄像头...")

    def update_confidence(self, value):
        """更新识别置信度"""
        confidence = value / 100.0  # 转换为0.0~1.0
        self.camera_thread.set_confidence(confidence)
        self.confidence_label.setText(f"{value}%")

    def closeEvent(self, event):
        """窗口关闭时释放资源"""
        if self.camera_thread.is_running:
            self.camera_thread.stop()
        event.accept()


if __name__ == "__main__":
    # 解决PyQt5与OpenCV的Qt版本冲突（部分环境需添加）
    import os

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""

    app = QApplication(sys.argv)
    window = GestureRecognitionWindow()
    window.show()
    sys.exit(app.exec_())