# -*- coding: utf-8 -*-
"""
@File    : 1.py
@Author  : qy
@Date    : 2025/8/22 15:44
"""
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit,
                             QAction, QFileDialog, QMessageBox)


class Notepad(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.text_edit = QTextEdit(self)
        self.setCentralWidget(self.text_edit)

        self.create_actions()
        self.create_menus()

        self.setWindowTitle('简易记事本')
        self.setGeometry(100, 100, 800, 600)

    def create_actions(self):
        # 文件菜单动作
        self.new_action = QAction('新建', self)
        self.new_action.setShortcut('Ctrl+N')
        self.new_action.triggered.connect(self.new_file)

        self.open_action = QAction('打开', self)
        self.open_action.setShortcut('Ctrl+O')
        self.open_action.triggered.connect(self.open_file)

        self.save_action = QAction('保存', self)
        self.save_action.setShortcut('Ctrl+S')
        self.save_action.triggered.connect(self.save_file)

        self.exit_action = QAction('退出', self)
        self.exit_action.setShortcut('Ctrl+Q')
        self.exit_action.triggered.connect(self.close)

        # 编辑菜单动作
        self.copy_action = QAction('复制', self)
        self.copy_action.setShortcut('Ctrl+C')
        self.copy_action.triggered.connect(self.text_edit.copy)

        self.paste_action = QAction('粘贴', self)
        self.paste_action.setShortcut('Ctrl+V')
        self.paste_action.triggered.connect(self.text_edit.paste)

        self.cut_action = QAction('剪切', self)
        self.cut_action.setShortcut('Ctrl+X')
        self.cut_action.triggered.connect(self.text_edit.cut)

    def create_menus(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu('文件')
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu('编辑')
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)
        edit_menu.addAction(self.cut_action)

    def new_file(self):
        self.text_edit.clear()

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, '打开文件')
        if filename:
            try:
                with open(filename, 'r') as f:
                    self.text_edit.setText(f.read())
            except Exception as e:
                QMessageBox.warning(self, '错误', f'无法打开文件: {e}')

    def save_file(self):
        filename, _ = QFileDialog.getSaveFileName(self, '保存文件')
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.text_edit.toPlainText())
            except Exception as e:
                QMessageBox.warning(self, '错误', f'无法保存文件: {e}')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    notepad = Notepad()
    notepad.show()
    sys.exit(app.exec_())