#!/usr/bin/env python3
import os
import sys
import shutil
import hashlib
import subprocess
import tempfile
import json
from pathlib import Path
import shlex

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QStackedWidget, QTextEdit,
    QProgressBar, QMessageBox, QCheckBox, QSpinBox, QComboBox, QListWidget,
    QListWidgetItem, QGroupBox, QFormLayout, QPlainTextEdit, QFrame
)

APP_NAME = "KlopatraKindom ISO Builder"
APP_VERSION = "1.0"
MIN_DISK_GB = 15

def run_cmd(cmd, cwd=None, timeout=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        timeout=timeout,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

def command_exists(name):
    return shutil.which(name) is not None

def filesystem_type(path):
    try:
        r = subprocess.run(["stat", "-f", "-c", "%T", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode == 0:
            return r.stdout.strip().lower()
    except Exception:
        pass
    return ""

def human_size(size):
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(size)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.1f} {unit}"
        n /= 1024

class Worker(QThread):
    output = pyqtSignal(str)
    progress = pyqtSignal(int)
    done = pyqtSignal(bool, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def write(self, text):
        self.output.emit(str(text))

    def run(self):
        try:
            result = self.fn(self.write, self.progress)
            self.done.emit(True, str(result or ""))
        except Exception as e:
            self.done.emit(False, str(e))

class StepPage(QWidget):
    def __init__(self, title, subtitle=""):
        super().__init__()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(36, 28, 36, 28)
        self.root.setSpacing(18)

        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.root.addWidget(self.title)

        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        self.root.addWidget(self.subtitle)

class Builder(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(980, 650)

        self.source_iso = None
        self.project_dir = None
        self.iso_root = None
        self.chroot_root = None
        self.squashfs_source = None
        self.squashfs_work = None
        self.original_squashfs_name = None
        self.output_iso = None
        self.worker = None
        self.steps = []
        self.current_step = 0
        self.project_state_file = None

        self.build_ui()
        self.install_autosave_hooks()
        self.apply_style()
        self.check_dependencies()
        self.update_buttons()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(30, 18, 30, 18)

        brand = QLabel("KlopatraKindom")
        brand.setObjectName("brand")
        hl.addWidget(brand)

        wizard = QLabel("ISO Builder")
        wizard.setObjectName("wizardName")
        hl.addWidget(wizard)

        hl.addStretch()

        self.step_label = QLabel()
        self.step_label.setObjectName("stepLabel")
        hl.addWidget(self.step_label)

        outer.addWidget(header)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(30, 14, 30, 14)

        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("statusLabel")
        fl.addWidget(self.status_label)
        fl.addStretch()

        self.back_btn = QPushButton("Назад")
        self.back_btn.clicked.connect(self.back)
        fl.addWidget(self.back_btn)

        self.next_btn = QPushButton("Далее")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.next)
        fl.addWidget(self.next_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.close)
        fl.addWidget(self.cancel_btn)

        outer.addWidget(footer)

        self.make_project_page()
        self.make_extract_page()
        self.make_packages_page()
        self.make_chroot_page()
        self.make_files_page()
        self.make_options_page()
        self.make_boot_page()
        self.make_generate_page()
        self.make_test_page()
        self.make_finish_page()

    def add_page(self, page):
        self.steps.append(page)
        self.stack.addWidget(page)

    def make_project_page(self):
        page = StepPage(
            "Проект",
            "Создайте проект на основе оригинального ISO. Builder рассчитан на Zorin OS 18.1 Pro и сохраняет исходную загрузочную структуру."
        )

        box = QGroupBox("Исходный ISO")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("Выберите Zorin OS 18.1 Pro ISO")
        row.addWidget(self.iso_edit, 1)
        b = QPushButton("Обзор…")
        b.clicked.connect(self.choose_iso)
        row.addWidget(b)
        form.addRow("ISO:", row)

        row2 = QHBoxLayout()
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("Каталог проекта")
        row2.addWidget(self.project_edit, 1)
        b2 = QPushButton("Обзор…")
        b2.clicked.connect(self.choose_project)
        row2.addWidget(b2)
        form.addRow("Проект:", row2)

        resume_row = QHBoxLayout()
        self.open_project_btn = QPushButton("Открыть существующий проект")
        self.open_project_btn.clicked.connect(self.open_existing_project)
        resume_row.addWidget(self.open_project_btn)
        self.save_project_btn = QPushButton("Сохранить проект")
        self.save_project_btn.clicked.connect(self.save_project_state)
        resume_row.addWidget(self.save_project_btn)
        resume_row.addStretch()
        page.root.addLayout(resume_row)

        self.name_edit = QLineEdit("KlopatraKindom")
        self.version_edit = QLineEdit("18.1")
        self.label_edit = QLineEdit("KlopatraKindom")

        form.addRow("Название:", self.name_edit)
        form.addRow("Версия:", self.version_edit)
        form.addRow("Метка ISO:", self.label_edit)

        page.root.addWidget(box)

        info = QGroupBox("Обнаружение")
        il = QGridLayout(info)
        self.detect_label = QLabel("ISO ещё не выбран")
        self.detect_label.setWordWrap(True)
        il.addWidget(self.detect_label, 0, 0, 1, 2)
        page.root.addWidget(info)

        page.root.addStretch()
        self.add_page(page)

    def make_extract_page(self):
        page = StepPage(
            "Распаковка",
            "ISO будет распакован в рабочий каталог, затем будет извлечена файловая система SquashFS."
        )

        self.extract_info = QLabel("Нажмите «Далее», чтобы начать.")
        self.extract_info.setObjectName("infoBox")
        self.extract_info.setWordWrap(True)
        page.root.addWidget(self.extract_info)

        self.extract_progress = QProgressBar()
        self.extract_progress.setRange(0, 100)
        page.root.addWidget(self.extract_progress)

        self.extract_log = QPlainTextEdit()
        self.extract_log.setReadOnly(True)
        page.root.addWidget(self.extract_log, 1)

        self.add_page(page)

    def make_packages_page(self):
        page = StepPage(
            "Пакеты",
            "Укажите пакеты для установки или удаления. Изменения выполняются внутри распакованной системы."
        )

        grid = QGridLayout()

        install_box = QGroupBox("Установить")
        il = QVBoxLayout(install_box)
        self.install_edit = QLineEdit()
        self.install_edit.setPlaceholderText("firefox vlc gimp")
        il.addWidget(self.install_edit)
        grid.addWidget(install_box, 0, 0)

        remove_box = QGroupBox("Удалить")
        rl = QVBoxLayout(remove_box)
        self.remove_edit = QLineEdit()
        self.remove_edit.setPlaceholderText("package1 package2")
        rl.addWidget(self.remove_edit)
        grid.addWidget(remove_box, 0, 1)

        deb_box = QGroupBox("DEB")
        dl = QVBoxLayout(deb_box)
        deb_row = QHBoxLayout()
        self.deb_edit = QLineEdit()
        deb_row.addWidget(self.deb_edit, 1)
        db = QPushButton("Добавить…")
        db.clicked.connect(self.choose_deb)
        deb_row.addWidget(db)
        dl.addLayout(deb_row)
        grid.addWidget(deb_box, 1, 0, 1, 2)

        page.root.addLayout(grid)

        self.update_packages_check = QCheckBox("Обновить списки APT перед установкой")
        page.root.addWidget(self.update_packages_check)

        self.package_log = QPlainTextEdit()
        self.package_log.setReadOnly(True)
        page.root.addWidget(self.package_log, 1)

        self.add_page(page)

    def make_chroot_page(self):
        page = StepPage(
            "CHROOT",
            "Выполняйте команды непосредственно внутри будущей установленной системы."
        )

        self.chroot_command = QLineEdit()
        self.chroot_command.setPlaceholderText("Например: apt install neofetch")
        page.root.addWidget(self.chroot_command)

        row = QHBoxLayout()
        self.chroot_run = QPushButton("Выполнить")
        self.chroot_run.clicked.connect(self.run_chroot_command)
        row.addWidget(self.chroot_run)

        self.chroot_shell = QPushButton("Открыть shell")
        self.chroot_shell.clicked.connect(self.open_chroot_shell)
        row.addWidget(self.chroot_shell)

        row.addStretch()
        page.root.addLayout(row)

        self.chroot_log = QPlainTextEdit()
        self.chroot_log.setReadOnly(True)
        page.root.addWidget(self.chroot_log, 1)

        self.add_page(page)

    def make_files_page(self):
        page = StepPage(
            "Файлы",
            "Добавляйте файлы и каталоги в будущую систему."
        )

        row = QHBoxLayout()

        self.file_target = QLineEdit("/")
        self.file_target.setPlaceholderText("Путь внутри системы")
        row.addWidget(self.file_target, 1)

        add = QPushButton("Добавить файл…")
        add.clicked.connect(self.add_file)
        row.addWidget(add)

        add_dir = QPushButton("Добавить каталог…")
        add_dir.clicked.connect(self.add_directory)
        row.addWidget(add_dir)

        page.root.addLayout(row)

        self.files_list = QListWidget()
        page.root.addWidget(self.files_list, 1)

        remove = QPushButton("Удалить выбранный элемент из списка")
        remove.clicked.connect(self.remove_file_entry)
        page.root.addWidget(remove)

        self.file_entries = []
        self.add_page(page)

    def make_options_page(self):
        page = StepPage(
            "Параметры",
            "Настройте базовые параметры системы и финальную очистку перед сборкой."
        )

        box = QGroupBox("Система")
        form = QFormLayout(box)

        self.hostname_edit = QLineEdit("kleopatra")
        form.addRow("Hostname:", self.hostname_edit)

        self.locale_combo = QComboBox()
        locales = [
            "en_US.UTF-8", "uk_UA.UTF-8", "ru_RU.UTF-8",
            "de_DE.UTF-8", "fr_FR.UTF-8", "es_ES.UTF-8",
            "it_IT.UTF-8", "pl_PL.UTF-8", "pt_BR.UTF-8",
            "tr_TR.UTF-8", "ja_JP.UTF-8", "ko_KR.UTF-8",
            "zh_CN.UTF-8"
        ]
        self.locale_combo.addItems(locales)
        self.locale_combo.setCurrentText("en_US.UTF-8")
        form.addRow("Локаль:", self.locale_combo)

        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["xz", "zstd", "gzip", "lzo", "lz4"])
        self.compression_combo.setCurrentText("xz")
        form.addRow("SquashFS:", self.compression_combo)

        self.processors_spin = QSpinBox()
        self.processors_spin.setRange(1, max(1, os.cpu_count() or 1))
        self.processors_spin.setValue(max(1, os.cpu_count() or 1))
        form.addRow("Процессоры:", self.processors_spin)

        page.root.addWidget(box)

        self.clean_apt = QCheckBox("Очистить кэш APT")
        self.clean_apt.setChecked(True)
        page.root.addWidget(self.clean_apt)

        self.clean_logs = QCheckBox("Очистить журналы")
        self.clean_logs.setChecked(True)
        page.root.addWidget(self.clean_logs)

        self.regen_manifest = QCheckBox("Перегенерировать filesystem.manifest")
        self.regen_manifest.setChecked(True)
        page.root.addWidget(self.regen_manifest)

        self.cleanup_tmp = QCheckBox("Очистить временные каталоги")
        self.cleanup_tmp.setChecked(True)
        page.root.addWidget(self.cleanup_tmp)

        page.root.addStretch()
        self.add_page(page)

    def make_boot_page(self):
        page = StepPage(
            "Boot",
            "Проверьте загрузочные конфигурации. Исходная схема загрузки ISO будет сохранена через xorriso."
        )

        self.boot_files = QListWidget()
        page.root.addWidget(self.boot_files, 1)

        row = QHBoxLayout()
        edit = QPushButton("Открыть выбранный")
        edit.clicked.connect(self.edit_boot_file)
        row.addWidget(edit)

        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self.refresh_boot_files)
        row.addWidget(refresh)

        row.addStretch()
        page.root.addLayout(row)

        self.boot_status = QLabel("Загрузочные файлы ещё не обнаружены.")
        self.boot_status.setObjectName("infoBox")
        self.boot_status.setWordWrap(True)
        page.root.addWidget(self.boot_status)

        self.add_page(page)

    def make_generate_page(self):
        page = StepPage(
            "Генерация ISO",
            "Будет создан новый ISO с изменённой SquashFS и сохранённой загрузочной структурой исходного образа."
        )

        box = QGroupBox("Выходной файл")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        row.addWidget(self.output_edit, 1)
        b = QPushButton("Обзор…")
        b.clicked.connect(self.choose_output)
        row.addWidget(b)
        form.addRow("ISO:", row)

        page.root.addWidget(box)

        self.generate_progress = QProgressBar()
        page.root.addWidget(self.generate_progress)

        self.generate_log = QPlainTextEdit()
        self.generate_log.setReadOnly(True)
        page.root.addWidget(self.generate_log, 1)

        self.add_page(page)

    def make_test_page(self):
        page = StepPage(
            "Тест",
            "Запустите созданный ISO в QEMU для проверки загрузки."
        )

        self.qemu_info = QLabel("QEMU не запускался.")
        self.qemu_info.setObjectName("infoBox")
        self.qemu_info.setWordWrap(True)
        page.root.addWidget(self.qemu_info)

        row = QHBoxLayout()

        self.qemu_ram = QSpinBox()
        self.qemu_ram.setRange(1024, 32768)
        self.qemu_ram.setValue(4096)
        self.qemu_ram.setSuffix(" MB")
        row.addWidget(QLabel("RAM:"))
        row.addWidget(self.qemu_ram)

        self.qemu_cpu = QSpinBox()
        self.qemu_cpu.setRange(1, 32)
        self.qemu_cpu.setValue(4)
        row.addWidget(QLabel("CPU:"))
        row.addWidget(self.qemu_cpu)

        row.addStretch()

        self.qemu_btn = QPushButton("Запустить QEMU")
        self.qemu_btn.clicked.connect(self.run_qemu)
        row.addWidget(self.qemu_btn)

        page.root.addLayout(row)

        self.qemu_log = QPlainTextEdit()
        self.qemu_log.setReadOnly(True)
        page.root.addWidget(self.qemu_log, 1)

        self.add_page(page)

    def make_finish_page(self):
        page = StepPage(
            "Готово",
            "Проект завершён."
        )

        self.finish_title = QLabel("ISO готов")
        self.finish_title.setObjectName("finishTitle")
        page.root.addWidget(self.finish_title)

        self.finish_info = QLabel()
        self.finish_info.setWordWrap(True)
        page.root.addWidget(self.finish_info)

        self.finish_hash = QLabel()
        self.finish_hash.setWordWrap(True)
        page.root.addWidget(self.finish_hash)

        open_btn = QPushButton("Открыть каталог")
        open_btn.clicked.connect(self.open_output_dir)
        page.root.addWidget(open_btn)

        page.root.addStretch()
        self.add_page(page)

    def apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background: #f5f6f8;
                color: #202124;
                font-size: 14px;
            }
            QMainWindow {
                background: #f5f6f8;
            }
            #header {
                background: #ffffff;
                border-bottom: 1px solid #d9dce1;
            }
            #brand {
                font-size: 22px;
                font-weight: 700;
            }
            #wizardName {
                font-size: 17px;
                margin-left: 12px;
                color: #62666d;
            }
            #stepLabel {
                color: #62666d;
                font-weight: 600;
            }
            #footer {
                background: #ffffff;
                border-top: 1px solid #d9dce1;
            }
            #statusLabel {
                color: #62666d;
            }
            #pageTitle {
                font-size: 30px;
                font-weight: 700;
            }
            #pageSubtitle {
                color: #62666d;
                font-size: 15px;
            }
            #infoBox {
                background: #ffffff;
                border: 1px solid #d9dce1;
                border-radius: 8px;
                padding: 14px;
            }
            #finishTitle {
                font-size: 32px;
                font-weight: 700;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d9dce1;
                border-radius: 8px;
                margin-top: 12px;
                padding: 14px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 5px;
            }
            QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox, QSpinBox {
                background: #ffffff;
                border: 1px solid #cfd3d9;
                border-radius: 6px;
                padding: 7px;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #cfd3d9;
                border-radius: 6px;
                padding: 9px 16px;
                min-height: 20px;
            }
            QPushButton:hover {
                background: #eef0f3;
            }
            QPushButton#primary {
                background: #2f343b;
                color: #ffffff;
                border-color: #2f343b;
                min-width: 100px;
            }
            QPushButton#primary:hover {
                background: #1f2328;
            }
            QProgressBar {
                background: #ffffff;
                border: 1px solid #cfd3d9;
                border-radius: 6px;
                text-align: center;
                min-height: 22px;
            }
            QProgressBar::chunk {
                background: #555b63;
                border-radius: 5px;
            }
            QCheckBox {
                spacing: 8px;
                padding: 6px;
            }
        """)

    def check_dependencies(self):
        required = ["xorriso", "unsquashfs", "mksquashfs", "rsync", "mount", "umount", "chroot"]
        missing = [x for x in required if not command_exists(x)]
        if missing:
            self.status_label.setText("Не хватает: " + ", ".join(missing))
        else:
            self.status_label.setText("Зависимости найдены")

    def install_autosave_hooks(self):
        for widget in [
            self.iso_edit, self.project_edit, self.name_edit, self.version_edit,
            self.label_edit, self.output_edit, self.hostname_edit,
            self.install_edit, self.remove_edit, self.deb_edit, self.chroot_command
        ]:
            widget.textChanged.connect(self.save_project_state)
        self.locale_combo.currentTextChanged.connect(self.save_project_state)
        self.compression_combo.currentTextChanged.connect(self.save_project_state)
        self.processors_spin.valueChanged.connect(self.save_project_state)
        for widget in [
            self.clean_apt, self.clean_logs, self.regen_manifest,
            self.cleanup_tmp, self.update_packages_check
        ]:
            widget.stateChanged.connect(self.save_project_state)

    def closeEvent(self, event):
        self.save_project_state()
        event.accept()

    def choose_iso(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите ISO", "", "ISO images (*.iso);;All files (*)"
        )
        if not path:
            return
        self.iso_edit.setText(path)
        self.source_iso = Path(path)
        self.detect_source()

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(self, "Каталог проекта")
        if path:
            self.project_edit.setText(path)
            self.project_dir = Path(path)
            self.project_state_file = self.project_dir / "project.json"
            if self.project_state_file.exists():
                reply = QMessageBox.question(
                    self,
                    "Существующий проект",
                    "В этом каталоге уже есть сохранённый проект. Продолжить его?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.load_project_state(self.project_state_file)

    def open_existing_project(self):
        path = QFileDialog.getExistingDirectory(self, "Открыть существующий проект")
        if not path:
            return
        state_file = Path(path) / "project.json"
        if not state_file.exists():
            QMessageBox.warning(self, "Проект", "В выбранном каталоге нет project.json.")
            return
        if not self.load_project_state(state_file):
            return
        self.status_label.setText("Проект продолжен")
        self.update_buttons()

    def save_project_state(self):
        if not self.project_dir:
            return
        try:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            state_file = self.project_dir / "project.json"
            data = {
                "format": 2,
                "app": APP_NAME,
                "version": APP_VERSION,
                "source_iso": str(self.source_iso) if self.source_iso else self.iso_edit.text().strip(),
                "project_dir": str(self.project_dir),
                "current_step": int(self.current_step),
                "name": self.name_edit.text(),
                "version_name": self.version_edit.text(),
                "label": self.label_edit.text(),
                "output_iso": self.output_edit.text().strip(),
                "hostname": self.hostname_edit.text(),
                "locale": self.locale_combo.currentText(),
                "compression": self.compression_combo.currentText(),
                "processors": self.processors_spin.value(),
                "clean_apt": self.clean_apt.isChecked(),
                "clean_logs": self.clean_logs.isChecked(),
                "regen_manifest": self.regen_manifest.isChecked(),
                "cleanup_tmp": self.cleanup_tmp.isChecked(),
                "update_packages": self.update_packages_check.isChecked(),
                "install_packages": self.install_edit.text(),
                "remove_packages": self.remove_edit.text(),
                "deb": self.deb_edit.text(),
                "chroot_command": self.chroot_command.text(),
                "file_entries": self.file_entries,
                "boot_files": [self.boot_files.item(i).text() for i in range(self.boot_files.count())],
                "original_squashfs_name": self.original_squashfs_name,
                "iso_root": str(self.iso_root) if self.iso_root else "",
                "chroot_root": str(self.chroot_root) if self.chroot_root else "",
                "squashfs_source": str(self.squashfs_source) if self.squashfs_source else "",
                "output_ready": bool(self.output_iso and self.output_iso.exists())
            }
            state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.project_state_file = state_file
        except Exception as e:
            self.status_label.setText(f"Ошибка сохранения: {e}")

    def load_project_state(self, state_file):
        try:
            state_file = Path(state_file).expanduser().resolve()
            data = json.loads(state_file.read_text(encoding="utf-8"))
            project = Path(data.get("project_dir") or state_file.parent).expanduser().resolve()
            source = Path(data.get("source_iso", "")).expanduser().resolve() if data.get("source_iso") else None

            self.project_dir = project
            self.project_state_file = state_file
            self.source_iso = source if source and source.exists() else None
            self.iso_edit.setText(str(source) if source else "")
            self.project_edit.setText(str(project))

            self.name_edit.setText(data.get("name", "KlopatraKindom"))
            self.version_edit.setText(data.get("version_name", "18.1"))
            self.label_edit.setText(data.get("label", "KlopatraKindom"))

            output = data.get("output_iso", "")
            self.output_edit.setText(output)
            self.output_iso = Path(output).expanduser().resolve() if output else None

            self.hostname_edit.setText(data.get("hostname", "kleopatra"))
            locale = data.get("locale", "en_US.UTF-8")
            if self.locale_combo.findText(locale) >= 0:
                self.locale_combo.setCurrentText(locale)
            compression = data.get("compression", "xz")
            if self.compression_combo.findText(compression) >= 0:
                self.compression_combo.setCurrentText(compression)
            self.processors_spin.setValue(max(1, min(self.processors_spin.maximum(), int(data.get("processors", os.cpu_count() or 1)))))
            self.clean_apt.setChecked(bool(data.get("clean_apt", True)))
            self.clean_logs.setChecked(bool(data.get("clean_logs", True)))
            self.regen_manifest.setChecked(bool(data.get("regen_manifest", True)))
            self.cleanup_tmp.setChecked(bool(data.get("cleanup_tmp", True)))
            self.update_packages_check.setChecked(bool(data.get("update_packages", False)))
            self.install_edit.setText(data.get("install_packages", ""))
            self.remove_edit.setText(data.get("remove_packages", ""))
            self.deb_edit.setText(data.get("deb", ""))
            self.chroot_command.setText(data.get("chroot_command", ""))

            self.file_entries = data.get("file_entries", [])
            self.files_list.clear()
            for entry in self.file_entries:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    self.files_list.addItem(f"{entry[0]} → {entry[1]}")

            self.original_squashfs_name = data.get("original_squashfs_name") or None
            iso_root = Path(data.get("iso_root", "")).expanduser().resolve() if data.get("iso_root") else project / "iso"
            chroot_root = Path(data.get("chroot_root", "")).expanduser().resolve() if data.get("chroot_root") else project / "chroot"
            squashfs_source = Path(data.get("squashfs_source", "")).expanduser().resolve() if data.get("squashfs_source") else None

            self.iso_root = iso_root if iso_root.exists() else None
            self.chroot_root = chroot_root if chroot_root.exists() else None
            self.squashfs_source = squashfs_source if squashfs_source else None
            self.squashfs_work = self.chroot_root

            if not self.squashfs_source and self.iso_root:
                found = list((self.iso_root / "casper").glob("*.squashfs")) if (self.iso_root / "casper").exists() else []
                if not found:
                    found = list(self.iso_root.rglob("*.squashfs"))
                if found:
                    self.squashfs_source = found[0]
                    self.original_squashfs_name = found[0].name

            if self.source_iso:
                self.detect_source()

            step = int(data.get("current_step", 0))
            ready = bool(self.iso_root and self.chroot_root and self.original_squashfs_name)
            if ready:
                step = max(1, min(9, step))
                self.extract_info.setText(
                    f"Существующий проект найден.\nISO: {self.iso_root}\nСистема: {self.chroot_root}\nSquashFS: {self.original_squashfs_name or 'найден'}"
                )
            else:
                step = 0

            self.current_step = step
            self.stack.setCurrentIndex(step)
            if step >= 6:
                self.refresh_boot_files()
            if step >= 7 and not self.output_edit.text() and self.project_dir:
                self.output_edit.setText(str(self.project_dir / "output" / "KlopatraKindom-18.1-custom.iso"))

            self.update_buttons()
            self.status_label.setText("Сохранённый проект открыт")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Открытие проекта", f"Не удалось открыть проект:\n{e}")
            return False

    def choose_deb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите DEB", "", "Debian packages (*.deb)"
        )
        if path:
            self.deb_edit.setText(path)

    def choose_output(self):
        default = str(self.project_dir / "output" / "KlopatraKindom-18.1-custom.iso") if self.project_dir else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить ISO", default, "ISO images (*.iso)"
        )
        if path:
            self.output_edit.setText(path)
            self.output_iso = Path(path)

    def detect_source(self):
        if not self.source_iso or not self.source_iso.exists():
            return
        try:
            r = run_cmd(["xorriso", "-indev", str(self.source_iso), "-pvd_info"], timeout=60)
            text = r.stdout
            self.detect_label.setText(text[:4000] if text else "Не удалось прочитать PVD.")
        except Exception as e:
            self.detect_label.setText(str(e))

    def validate_project(self):
        if not self.iso_edit.text().strip():
            QMessageBox.warning(self, "Проект", "Выберите исходный ISO.")
            return False
        if not self.project_edit.text().strip():
            QMessageBox.warning(self, "Проект", "Выберите каталог проекта.")
            return False
        self.source_iso = Path(self.iso_edit.text()).expanduser().resolve()
        self.project_dir = Path(self.project_edit.text()).expanduser().resolve()
        if not self.source_iso.exists():
            QMessageBox.warning(self, "Проект", "Исходный ISO не найден.")
            return False
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.project_state_file = self.project_dir / "project.json"
        self.save_project_state()
        return True

    def next(self):
        self.save_project_state()
        if self.current_step == 0:
            if not self.validate_project():
                return
            self.stack.setCurrentIndex(1)
            self.current_step = 1
            self.start_extract()
            self.update_buttons()
            return

        if self.current_step == 1:
            self.current_step = 2
            self.stack.setCurrentIndex(2)
            self.update_buttons()
            return

        if self.current_step == 2:
            self.current_step = 3
            self.stack.setCurrentIndex(3)
            self.update_buttons()
            return

        if self.current_step == 3:
            self.current_step = 4
            self.stack.setCurrentIndex(4)
            self.update_buttons()
            return

        if self.current_step == 4:
            self.current_step = 5
            self.stack.setCurrentIndex(5)
            self.update_buttons()
            return

        if self.current_step == 5:
            self.current_step = 6
            self.stack.setCurrentIndex(6)
            self.refresh_boot_files()
            self.update_buttons()
            return

        if self.current_step == 6:
            self.current_step = 7
            self.stack.setCurrentIndex(7)
            if not self.output_edit.text():
                self.output_edit.setText(
                    str(self.project_dir / "output" / "KlopatraKindom-18.1-custom.iso")
                )
            self.update_buttons()
            return

        if self.current_step == 7:
            self.current_step = 8
            self.stack.setCurrentIndex(8)
            self.start_generate()
            self.update_buttons()
            return

        if self.current_step == 8:
            self.current_step = 9
            self.stack.setCurrentIndex(9)
            self.prepare_finish()
            self.update_buttons()
            return

        if self.current_step == 9:
            self.close()

    def back(self):
        self.save_project_state()
        if self.current_step <= 0:
            return
        self.current_step -= 1
        self.stack.setCurrentIndex(self.current_step)
        self.update_buttons()

    def update_buttons(self):
        self.step_label.setText(f"Шаг {self.current_step + 1} из {len(self.steps)}")
        self.back_btn.setEnabled(self.current_step > 0)
        self.next_btn.setText("Готово" if self.current_step == 9 else "Далее")
        self.status_label.setText(self.steps[self.current_step].title.text())

    def start_worker(self, fn, log_widget=None, progress=None, finished=None):
        if self.worker and self.worker.isRunning():
            return
        self.worker = Worker(fn)
        if log_widget:
            self.worker.output.connect(log_widget.appendPlainText)
        if progress:
            self.worker.progress.connect(progress.setValue)
        if finished:
            self.worker.done.connect(finished)
        self.worker.start()

    def start_extract(self):
        if self.iso_root and self.chroot_root and self.original_squashfs_name and self.iso_root.exists() and self.chroot_root.exists():
            self.extract_info.setText(
                f"Сохранённый проект уже распакован.\nISO: {self.iso_root}\nСистема: {self.chroot_root}\nSquashFS: {self.original_squashfs_name or 'найден'}"
            )
            self.extract_progress.setValue(100)
            self.status_label.setText("Распаковка уже выполнена")
            self.save_project_state()
            return
        self.extract_log.clear()
        self.extract_progress.setValue(0)
        self.extract_info.setText("Подготовка…")

        def job(write, progress):
            project = self.project_dir
            if not project:
                raise RuntimeError("Каталог проекта не выбран.")
            project.mkdir(parents=True, exist_ok=True)
            fs_type = filesystem_type(project)
            unsupported = {"ntfs", "ntfs3", "fuseblk", "exfat", "fuse.exfat", "vfat", "msdos", "cifs", "smb2", "sshfs", "davfs", "fuse.sshfs"}
            if fs_type in unsupported:
                raise RuntimeError(
                    f"Каталог проекта находится на файловой системе {fs_type}, которая не поддерживает необходимые Linux-права для chroot. "
                    "Создайте рабочий проект на ext4, btrfs, xfs или другой Linux-файловой системе. "
                    "Исходный ISO и готовый ISO можно хранить на другом диске."
                )
            if not self.source_iso or not self.source_iso.exists():
                raise RuntimeError("Исходный ISO не найден.")

            iso_root = project / "iso"
            chroot = project / "chroot"
            squash = project / "squashfs"
            marker = project / ".extracting"
            existing_iso = iso_root.exists() and any(iso_root.iterdir())
            existing_chroot = chroot.exists() and any(chroot.iterdir())
            existing_squash = squash.exists() and any(squash.iterdir())
            valid_chroot = (chroot / "etc" / "os-release").is_file() and (chroot / "bin" / "bash").exists()
            valid_iso_tree = (iso_root / "casper").is_dir() and (iso_root / "boot").exists()

            if existing_chroot and valid_chroot and existing_iso and valid_iso_tree:
                self.iso_root = iso_root
                self.chroot_root = chroot
                self.squashfs_work = chroot
                if not self.original_squashfs_name:
                    self.original_squashfs_name = "filesystem.squashfs"
                self.squashfs_source = None
                marker_path = project / ".klopatra-kindom-chroot"
                try:
                    marker_path.write_text(str(chroot.resolve()) + "\n", encoding="utf-8")
                except Exception:
                    pass
                progress.emit(100)
                self.save_project_state()
                return "Существующий проект найден. Распаковка не выполняется. CHROOT готов для продолжения."

            if existing_iso or existing_chroot or existing_squash or marker.exists():
                raise RuntimeError(
                    "В каталоге проекта уже есть данные незавершённой распаковки. "
                    "Они не удаляются автоматически. Выберите этот проект для продолжения или новый пустой каталог."
                )

            iso_root.mkdir(parents=True, exist_ok=False)
            chroot.mkdir(parents=True, exist_ok=False)
            squash.mkdir(parents=True, exist_ok=False)
            marker.write_text("extracting\n", encoding="utf-8")

            write(f"Файловая система проекта: {fs_type or 'не определена'}")
            write("Одна привилегированная операция: подключение ISO → быстрое извлечение → SquashFS → отключение ISO.")
            write("pkexec будет вызван только один раз.")
            write("/var/lib/flatpak будет пропущен.")

            import shlex
            source_q = shlex.quote(str(self.source_iso))
            iso_root_q = shlex.quote(str(iso_root))
            chroot_q = shlex.quote(str(chroot))
            user_q = shlex.quote(str(os.getuid()))
            group_q = shlex.quote(str(os.getgid()))
            processors = max(1, self.processors_spin.value())
            processors_q = shlex.quote(str(processors))

            script = f'''set -u
MNT="$(mktemp -d /tmp/klopatra-iso-mount-XXXXXX)"
mounted=0
cleanup() {{
    if [ "$mounted" -eq 1 ]; then
        umount -l -- "$MNT" >/dev/null 2>&1 || umount -l -f -- "$MNT" >/dev/null 2>&1 || true
    fi
    rmdir "$MNT" >/dev/null 2>&1 || true
}}
trap cleanup EXIT
printf '%s\\n' "Подключение ISO: $MNT"
mount -o loop,ro -- {source_q} "$MNT"
mounted=1
printf '%s\\n' "ISO подключён."
SQ=""
if [ -d "$MNT/casper" ]; then
    SQ="$(find "$MNT/casper" -maxdepth 1 -type f -name '*.squashfs' -print -quit)"
fi
if [ -z "$SQ" ]; then
    SQ="$(find "$MNT" -type f -name '*.squashfs' -print -quit)"
fi
if [ -z "$SQ" ]; then
    printf '%s\\n' "ОШИБКА: SquashFS не найден."
    exit 20
fi
NAME="$(basename "$SQ")"
printf 'Найден SquashFS: %s\\n' "$SQ"
printf '%s\\n' "Извлечение ISO без копирования SquashFS…"
mkdir -p {iso_root_q}
tar -C "$MNT" --exclude="./casper/$NAME" --exclude="casper/$NAME" -cpf - . | tar -C {iso_root_q} -xpf -
PIPE=("${{PIPESTATUS[@]}}")
if [ "${{PIPE[0]}}" -ne 0 ] || [ "${{PIPE[1]}}" -ne 0 ]; then
    printf 'ОШИБКА извлечения ISO: tar=%s/%s\\n' "${{PIPE[0]}}" "${{PIPE[1]}}"
    exit 21
fi
if [ -e {iso_root_q}/casper/$NAME ]; then
    printf '%s\\n' "ОШИБКА: filesystem.squashfs всё ещё оказался в рабочем ISO-дереве."
    rm -f -- {iso_root_q}/casper/$NAME
    exit 22
fi
printf '%s\\n' "ISO-дерево извлечено без копирования SquashFS."
printf '%s\\n' "Распаковка SquashFS напрямую с подключённого ISO…"
printf '%s\\n' "Исключение: /var/lib/flatpak"
EXCLUDES="$(mktemp /tmp/klopatra-unsquashfs-exclude-XXXXXX)"
printf '%s\n' "var/lib/flatpak" > "$EXCLUDES"
unsquashfs -no-xattrs -processors {processors_q} -d {chroot_q} -exclude-file "$EXCLUDES" "$SQ"
U=$?
rm -f "$EXCLUDES"
if [ "$U" -ne 0 ]; then
    printf 'ОШИБКА unsquashfs: код %s\n' "$U"
    exit "$U"
fi
printf '%s\\n' "SquashFS распакован."
printf '%s\\n' "Отключение ISO внутри того же pkexec-процесса…"
if ! umount -l -- "$MNT"; then
    umount -l -f -- "$MNT" || {{ printf '%s\\n' "ОШИБКА: не удалось отключить ISO."; exit 30; }}
fi
mounted=0
printf '%s\\n' "ISO отключён."
chown -R --no-dereference {user_q}:{group_q} {iso_root_q}
printf '%s\\n' "Права ISO-дерева возвращены пользователю."
'''
            pk_env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"}
            r = run_cmd(["pkexec", "bash", "-c", script], timeout=7200, env=pk_env)
            write(r.stdout)
            if r.returncode != 0:
                details = r.stdout.strip() or "нет дополнительного сообщения"
                if "Request dismissed" in details:
                    raise RuntimeError("Запрос прав был отклонён. Подтвердите запрос пароля администратора.")
                if "Operation not permitted" in details or "Errno 1" in details:
                    raise RuntimeError(
                        "Распаковка завершилась с ошибкой Operation not permitted. Старый проект не удалён. "
                        "Проверьте, что каталог проекта находится на ext4/btrfs/xfs.\n\n" + details
                    )
                raise RuntimeError(f"Распаковка не завершена. Старые данные не удалялись.\n\n{details}")

            try:
                marker.unlink()
            except FileNotFoundError:
                pass

            os_release = chroot / "etc" / "os-release"
            if os_release.exists():
                content = os_release.read_text(errors="replace")
                write(content)
                if "ID=zorin" in content or 'ID="zorin"' in content:
                    if "18.1" in content:
                        write("Обнаружен Zorin OS 18.1.")
                    else:
                        write("Обнаружен Zorin OS, но версия отличается от 18.1.")
            else:
                write("etc/os-release не найден.")

            marker = project / ".klopatra-kindom-chroot"
            marker.write_text(str(chroot.resolve()) + "\n", encoding="utf-8")
            self.original_squashfs_name = self.original_squashfs_name or "filesystem.squashfs"
            self.iso_root = iso_root
            self.chroot_root = chroot
            self.squashfs_work = chroot
            self.squashfs_source = iso_root / "casper" / self.original_squashfs_name
            progress.emit(100)
            return "Распаковка завершена. ISO отключён в том же привилегированном процессе."

        def finished(ok, msg):
            if not ok:
                self.extract_info.setText("Ошибка: " + msg)
                QMessageBox.critical(self, "Распаковка", msg)
            else:
                self.extract_info.setText(msg)
            self.save_project_state()

        self.start_worker(job, self.extract_log, self.extract_progress, finished)

    def validate_chroot(self):
        root = self.chroot_root.resolve() if self.chroot_root else None
        if root is None or str(root) == "/":
            raise RuntimeError("ОПАСНО: каталог chroot не задан или указывает на корень хост-системы.")
        project = self.project_dir.resolve() if self.project_dir else None
        if project is None or str(project) == "/":
            raise RuntimeError("ОПАСНО: каталог проекта не задан.")
        marker = project / ".klopatra-kindom-chroot"
        os_release = root / "etc" / "os-release"
        bash = root / "bin" / "bash"
        expected_root = (project / "chroot").resolve()
        if root != expected_root:
            raise RuntimeError("Каталог chroot не совпадает с project/chroot. Команда остановлена, хост-система не затрагивается.")
        if not os_release.is_file() or not bash.is_file():
            raise RuntimeError("Каталог chroot не содержит системные файлы. Команда остановлена, хост-система не затрагивается.")
        if marker.is_file():
            try:
                marked = Path(marker.read_text(encoding="utf-8").strip()).resolve()
            except Exception:
                raise RuntimeError("Защитный маркер повреждён. Команда остановлена.")
            if marked != root:
                raise RuntimeError("Защитный маркер не соответствует project/chroot. Команда остановлена, хост-система не затрагивается.")
        else:
            marker.write_text(str(root) + "\n", encoding="utf-8")
        return root

    def chroot_command(self, command, timeout=3600, env=None):
        root = self.validate_chroot()
        self.mount_chroot()
        try:
            safe_env = os.environ.copy()
            safe_env["DEBIAN_FRONTEND"] = "noninteractive"
            if env:
                safe_env.update(env)
            return run_cmd(["pkexec", "chroot", str(root), "/bin/bash", "-lc", command], timeout=timeout, env=safe_env)
        finally:
            self.unmount_chroot()

    def mount_chroot(self):
        root = self.chroot_root
        if not root:
            raise RuntimeError("Система ещё не распакована.")

        binds = [
            ("proc", root / "proc", ["mount", "-t", "proc", "proc", str(root / "proc")]),
            ("sys", root / "sys", ["mount", "--rbind", "/sys", str(root / "sys")]),
            ("dev", root / "dev", ["mount", "--rbind", "/dev", str(root / "dev")]),
            ("run", root / "run", ["mount", "--rbind", "/run", str(root / "run")])
        ]

        for _, target, cmd in binds:
            target.mkdir(parents=True, exist_ok=True)
            r = run_cmd(["pkexec"] + cmd, timeout=120)
            if r.returncode != 0:
                self.unmount_chroot()
                raise RuntimeError(r.stdout)

    def unmount_chroot(self):
        root = self.chroot_root
        if not root:
            return
        for name in ["run", "dev", "sys", "proc"]:
            target = root / name
            if target.exists():
                run_cmd(["pkexec", "umount", "-R", str(target)], timeout=120)

    def run_chroot_command(self):
        command = self.chroot_command.text().strip()
        if not command:
            return

        def job(write, progress):
            r = self.chroot_command(command, timeout=3600)
            write(r.stdout)
            if r.returncode != 0:
                raise RuntimeError(r.stdout)
            return "Команда выполнена внутри KlopatraKindom chroot."

        self.start_worker(job, self.chroot_log, None, lambda ok, msg: None)

    def open_chroot_shell(self):
        try:
            root = self.validate_chroot()
        except Exception as e:
            QMessageBox.critical(self, "CHROOT", str(e))
            return
        if not (root / "bin" / "bash").is_file() or not (root / "etc" / "os-release").is_file():
            QMessageBox.critical(self, "CHROOT", "Каталог chroot не является полноценной системой.")
            return
        fd, script_path = tempfile.mkstemp(prefix="klopatra-kindom-shell-", suffix=".sh", dir="/tmp")
        os.close(fd)
        script = Path(script_path)
        script.chmod(0o755)
        script.write_text('#!/bin/bash\nset -Eeuo pipefail\nROOT=__ROOT__\ncleanup() {\n    umount -R "$ROOT/run" 2>/dev/null || true\n    umount -R "$ROOT/dev" 2>/dev/null || true\n    umount -R "$ROOT/sys" 2>/dev/null || true\n    umount -R "$ROOT/proc" 2>/dev/null || true\n    rm -f -- "$0" 2>/dev/null || true\n}\ntrap cleanup EXIT\nif [ "$(id -u)" -ne 0 ]; then\n    echo "ОШИБКА: Shell должен быть запущен через pkexec."\n    exit 1\nfi\nif [ "$ROOT" = "/" ] || [ ! -f "$ROOT/etc/os-release" ] || [ ! -x "$ROOT/bin/bash" ]; then\n    echo "ОШИБКА: недопустимый CHROOT: $ROOT"\n    exit 1\nfi\nmkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev" "$ROOT/run"\nmount -t proc proc "$ROOT/proc"\nmount --rbind /sys "$ROOT/sys"\nmount --make-rslave "$ROOT/sys"\nmount --rbind /dev "$ROOT/dev"\nmount --make-rslave "$ROOT/dev"\nmount --rbind /run "$ROOT/run"\nmount --make-rslave "$ROOT/run"\nprintf \'\\n=== KlopatraKindom CHROOT ===\\n\'\nprintf \'ROOT=%s\\n\' "$ROOT"\nprintf \'Вход выполнен. Для выхода: exit\\n\\n\'\nexport HOME=/root\nexport TERM="${TERM:-xterm-256color}"\nexport LANG=C.UTF-8\nexport LC_ALL=C.UTF-8\nexport PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\nexec chroot "$ROOT" /bin/bash --login -i\n'.replace("__ROOT__", shlex.quote(str(root))), encoding="utf-8")
        try:
            if shutil.which("gnome-terminal"):
                subprocess.Popen(["gnome-terminal", "--title=KlopatraKindom CHROOT", "--", "pkexec", "/bin/bash", str(script)], start_new_session=True)
            elif shutil.which("konsole"):
                subprocess.Popen(["konsole", "--hold", "-e", "pkexec", "/bin/bash", str(script)], start_new_session=True)
            elif shutil.which("xfce4-terminal"):
                subprocess.Popen(["xfce4-terminal", "--hold", "-e", f"pkexec /bin/bash {shlex.quote(str(script))}"], start_new_session=True)
            elif shutil.which("x-terminal-emulator"):
                subprocess.Popen(["x-terminal-emulator", "-e", "pkexec", "/bin/bash", str(script)], start_new_session=True)
            elif shutil.which("xterm"):
                subprocess.Popen(["xterm", "-hold", "-title", "KlopatraKindom CHROOT", "-e", "pkexec", "/bin/bash", str(script)], start_new_session=True)
            else:
                raise RuntimeError("Не найден терминал. Установите gnome-terminal.")
        except Exception as e:
            try:
                script.unlink()
            except Exception:
                pass
            QMessageBox.critical(self, "CHROOT", str(e))

    def choose_file_common(self, directory=False):
        if directory:
            return QFileDialog.getExistingDirectory(self, "Выберите каталог")
        return QFileDialog.getOpenFileName(self, "Выберите файл", "", "All files (*)")[0]

    def add_file(self):
        src = self.choose_file_common(False)
        if not src:
            return
        target = self.file_target.text().strip() or "/"
        self.file_entries.append((src, target, False))
        self.files_list.addItem(f"{src} → {target}")

    def add_directory(self):
        src = self.choose_file_common(True)
        if not src:
            return
        target = self.file_target.text().strip() or "/"
        self.file_entries.append((src, target, True))
        self.files_list.addItem(f"{src} → {target}")

    def remove_file_entry(self):
        row = self.files_list.currentRow()
        if row >= 0:
            self.files_list.takeItem(row)
            self.file_entries.pop(row)

    def apply_file_entries(self):
        for src, target, is_dir in self.file_entries:
            source = str(Path(src).expanduser().resolve())
            target_path = self.chroot_root / target.lstrip("/")
            source_q = source.replace("'", "'\\''")
            target_q = str(target_path).replace("'", "'\\''")
            if is_dir:
                command = f"mkdir -p '{target_q}' && rsync -aHAX --numeric-ids '{source_q}/' '{target_q}/'"
            else:
                parent_q = str(target_path.parent).replace("'", "'\\''")
                command = f"mkdir -p '{parent_q}' && install -D -m 0644 -o root -g root '{source_q}' '{target_q}'"
            r = run_cmd(["pkexec", "bash", "-lc", command], timeout=1800)
            if r.returncode != 0:
                raise RuntimeError(r.stdout)

    def apply_options(self, write):
        if not self.chroot_root:
            raise RuntimeError("Система не распакована.")

        hostname = self.hostname_edit.text().strip()
        if hostname:
            host_file = self.project_dir / ".kleopatra-hostname"
            host_file.write_text(hostname + "\n")
            r = run_cmd(["pkexec", "install", "-o", "root", "-g", "root", "-m", "644", str(host_file), str(self.chroot_root / "etc/hostname")], timeout=120)
            host_file.unlink(missing_ok=True)
            if r.returncode != 0:
                raise RuntimeError(r.stdout)

            hosts = self.chroot_root / "etc/hosts"
            if hosts.exists():
                text = hosts.read_text(errors="replace")
                lines = []
                replaced = False
                for line in text.splitlines():
                    if line.strip() and not line.lstrip().startswith("#"):
                        parts = line.split()
                        if parts and parts[0] == "127.0.1.1":
                            if not replaced:
                                lines.append("127.0.1.1\t" + hostname)
                                replaced = True
                            continue
                    lines.append(line)
                if not replaced:
                    lines.append("127.0.1.1\t" + hostname)
                temp_hosts = self.project_dir / ".kleopatra-hosts"
                temp_hosts.write_text("\n".join(lines) + "\n")
                r = run_cmd(["pkexec", "install", "-o", "root", "-g", "root", "-m", "644", str(temp_hosts), str(hosts)], timeout=120)
                temp_hosts.unlink(missing_ok=True)
                if r.returncode != 0:
                    raise RuntimeError(r.stdout)

        locale = self.locale_combo.currentText()
        locale_file = self.project_dir / ".kleopatra-locale"
        locale_file.write_text(f"LANG={locale}\nLC_ALL={locale}\n")
        r = run_cmd(["pkexec", "install", "-D", "-o", "root", "-g", "root", "-m", "644", str(locale_file), str(self.chroot_root / "etc/default/locale")], timeout=120)
        locale_file.unlink(missing_ok=True)
        if r.returncode != 0:
            raise RuntimeError(r.stdout)

        if self.clean_apt.isChecked():
            r = run_cmd(["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", "rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb"], timeout=300)
            if r.returncode != 0:
                raise RuntimeError(r.stdout)

        if self.clean_logs.isChecked():
            run_cmd(["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", "find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null || true"], timeout=300)

        if self.cleanup_tmp.isChecked():
            run_cmd(["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", "find /tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; find /var/tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +"], timeout=300)

        if self.regen_manifest.isChecked():
            manifest = self.iso_root / "casper" / "filesystem.manifest"
            if manifest.parent.exists():
                r = run_cmd(["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", "dpkg-query -W --showformat='${Package} ${Version}\n'"], timeout=600)
                if r.returncode == 0:
                    manifest.write_text(r.stdout)

        write("Параметры применены с сохранением root:root и исходных режимов.")

    def process_packages(self):
        install = self.install_edit.text().strip()
        remove = self.remove_edit.text().strip()
        deb = self.deb_edit.text().strip()
        update = self.update_packages_check.isChecked()

        if not any([install, remove, deb, update]):
            return

        self.package_log.clear()

        def job(write, progress):
            self.mount_chroot()
            try:
                env = os.environ.copy()
                env["DEBIAN_FRONTEND"] = "noninteractive"

                if update:
                    write("apt update")
                    r = run_cmd(
                        ["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", "apt-get update"],
                        timeout=1800,
                        env=env
                    )
                    write(r.stdout)
                    if r.returncode != 0:
                        raise RuntimeError("apt update завершился ошибкой.")

                if install:
                    write("apt install " + install)
                    r = run_cmd(
                        ["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc",
                         "apt-get install -y " + install],
                        timeout=3600,
                        env=env
                    )
                    write(r.stdout)
                    if r.returncode != 0:
                        raise RuntimeError("Установка пакетов завершилась ошибкой.")

                if remove:
                    write("apt remove " + remove)
                    r = run_cmd(
                        ["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc",
                         "apt-get remove -y " + remove],
                        timeout=3600,
                        env=env
                    )
                    write(r.stdout)
                    if r.returncode != 0:
                        raise RuntimeError("Удаление пакетов завершилось ошибкой.")

                if deb:
                    source = Path(deb).expanduser().resolve()
                    if not source.exists():
                        raise RuntimeError("DEB не найден.")
                    target = self.chroot_root / "tmp" / source.name
                    source_q = str(source).replace("'", "'\\''")
                    target_q = str(target).replace("'", "'\\''")
                    root_q = str(self.chroot_root).replace("'", "'\\''")
                    command = f"install -D -m 0644 -o root -g root '{source_q}' '{target_q}' && chroot '{root_q}' /bin/bash -lc 'dpkg -i /tmp/{source.name} || apt-get -f install -y'; rm -f '{target_q}'"
                    r = run_cmd(["pkexec", "bash", "-lc", command], timeout=3600, env=env)
                    write(r.stdout)
                    if r.returncode != 0:
                        raise RuntimeError("Установка DEB завершилась ошибкой.")

                progress.emit(100)
                return "Операции с пакетами завершены."
            finally:
                self.unmount_chroot()

        def finished(ok, msg):
            if not ok:
                QMessageBox.critical(self, "Пакеты", msg)

        self.start_worker(job, self.package_log, None, finished)

    def refresh_boot_files(self):
        self.boot_files.clear()
        if not self.iso_root:
            return
        candidates = [
            self.iso_root / "boot" / "grub" / "grub.cfg",
            self.iso_root / "boot" / "grub" / "loopback.cfg",
            self.iso_root / "isolinux" / "menuentries.cfg",
            self.iso_root / "isolinux" / "isolinux.cfg",
            self.iso_root / "boot" / "grub" / "fonts"
        ]
        found = []
        for p in candidates:
            if p.exists():
                found.append(p)
        for p in found:
            item = QListWidgetItem(str(p.relative_to(self.iso_root)))
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self.boot_files.addItem(item)

        self.boot_status.setText(
            f"Найдено загрузочных элементов: {len(found)}. "
            "При генерации исходная boot-схема будет передана xorriso через replay."
        )

    def edit_boot_file(self):
        item = self.boot_files.currentItem()
        if not item:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if not path.is_file():
            return

        editor = QTextEdit()
        editor.setWindowTitle(str(path))
        editor.resize(900, 650)
        editor.setPlainText(path.read_text(errors="replace"))

        save = QPushButton("Сохранить")
        layout = QVBoxLayout()
        layout.addWidget(editor)
        layout.addWidget(save)

        dialog = QWidget()
        dialog.setWindowTitle(f"Редактор — {path.name}")
        dialog.setLayout(layout)
        dialog.resize(900, 700)

        def save_file():
            path.write_text(editor.toPlainText())
            dialog.close()

        save.clicked.connect(save_file)
        dialog.show()
        self.boot_editor_window = dialog

    def start_generate(self):
        self.generate_log.clear()
        self.generate_progress.setValue(0)
        self.output_iso = Path(self.output_edit.text()).expanduser().resolve()

        def job(write, progress):
            if not self.chroot_root or not self.iso_root or not self.original_squashfs_name:
                raise RuntimeError("Проект не подготовлен.")

            if self.output_iso == self.source_iso:
                raise RuntimeError("Выходной ISO не может совпадать с исходным ISO.")
            if not self.output_iso.parent.exists():
                self.output_iso.parent.mkdir(parents=True, exist_ok=True)

            write("Применение файлов…")
            self.apply_file_entries()

            write("Применение параметров…")
            self.apply_options(write)
            progress.emit(15)

            write("Очистка системы перед сборкой…")
            self.mount_chroot()
            try:
                commands = [
                    "rm -f /etc/machine-id",
                    "rm -f /var/lib/dbus/machine-id",
                    "rm -f /var/lib/systemd/random-seed"
                ]
                for cmd in commands:
                    run_cmd(["pkexec", "chroot", str(self.chroot_root), "/bin/bash", "-lc", cmd], timeout=120)
            finally:
                self.unmount_chroot()

            progress.emit(25)

            new_squash = self.project_dir / "squashfs" / self.original_squashfs_name
            new_squash.parent.mkdir(parents=True, exist_ok=True)
            if new_squash.exists():
                new_squash.unlink()

            write("Создание SquashFS…")
            processors = str(self.processors_spin.value())
            compression = self.compression_combo.currentText()

            r = run_cmd([
                "mksquashfs", str(self.chroot_root), str(new_squash),
                "-comp", compression, "-processors", processors,
                "-noappend"
            ], timeout=3600)
            write(r.stdout)
            if r.returncode != 0:
                raise RuntimeError("mksquashfs завершился ошибкой.")

            progress.emit(65)

            if self.regen_manifest.isChecked():
                manifest = self.iso_root / "casper" / "filesystem.manifest"
                if manifest.exists():
                    r = run_cmd(
                        ["dpkg-query", "-W", "--showformat=${Package} ${Version}\\n"],
                        cwd=str(self.chroot_root),
                        timeout=120
                    )
                    if r.returncode == 0:
                        manifest.write_text(r.stdout)

            write("Сборка bootable ISO через xorriso…")
            if self.output_iso.exists():
                self.output_iso.unlink()

            iso_target = "/casper/" + self.original_squashfs_name

            cmd = [
                "xorriso",
                "-indev", str(self.source_iso),
                "-outdev", str(self.output_iso),
                "-map", str(new_squash), iso_target
            ]

            boot_candidates = [
                (self.iso_root / "boot" / "grub" / "grub.cfg", "/boot/grub/grub.cfg"),
                (self.iso_root / "boot" / "grub" / "loopback.cfg", "/boot/grub/loopback.cfg"),
                (self.iso_root / "isolinux" / "menuentries.cfg", "/isolinux/menuentries.cfg"),
                (self.iso_root / "isolinux" / "isolinux.cfg", "/isolinux/isolinux.cfg")
            ]

            for local, iso_path in boot_candidates:
                if local.exists() and local.is_file():
                    cmd += ["-map", str(local), iso_path]

            cmd += ["-boot_image", "any", "replay", "-padding", "included"]

            r = run_cmd(cmd, timeout=3600)
            write(r.stdout)
            if r.returncode != 0:
                raise RuntimeError("xorriso завершился ошибкой.")

            progress.emit(90)

            sha = hashlib.sha256()
            with self.output_iso.open("rb") as f:
                while True:
                    block = f.read(1024 * 1024)
                    if not block:
                        break
                    sha.update(block)

            sha_path = self.output_iso.with_suffix(self.output_iso.suffix + ".sha256")
            sha_path.write_text(f"{sha.hexdigest()}  {self.output_iso.name}\n")

            progress.emit(100)
            return f"ISO создан: {self.output_iso}\nSHA256: {sha.hexdigest()}"

        def finished(ok, msg):
            if not ok:
                QMessageBox.critical(self, "Генерация ISO", msg)
            else:
                self.qemu_info.setText(f"ISO готов к тесту.\n{self.output_iso}")
            self.save_project_state()

        self.start_worker(job, self.generate_log, self.generate_progress, finished)

    def run_qemu(self):
        if not self.output_iso or not self.output_iso.exists():
            QMessageBox.warning(self, "QEMU", "Сначала создайте ISO.")
            return
        if not command_exists("qemu-system-x86_64"):
            QMessageBox.warning(self, "QEMU", "qemu-system-x86_64 не найден.")
            return

        self.qemu_log.appendPlainText("Запуск QEMU…")
        cmd = [
            "qemu-system-x86_64",
            "-m", str(self.qemu_ram.value()),
            "-smp", str(self.qemu_cpu.value()),
            "-cdrom", str(self.output_iso),
            "-boot", "d"
        ]
        if command_exists("kvm-ok") and os.path.exists("/dev/kvm"):
            cmd += ["-enable-kvm"]

        try:
            subprocess.Popen(cmd)
            self.qemu_info.setText("QEMU запущен.")
        except Exception as e:
            self.qemu_log.appendPlainText(str(e))

    def prepare_finish(self):
        if not self.output_iso or not self.output_iso.exists():
            self.finish_title.setText("ISO не найден")
            self.finish_info.setText("Генерация не завершилась успешно.")
            self.finish_hash.setText("")
            return

        sha = hashlib.sha256()
        with self.output_iso.open("rb") as f:
            while True:
                block = f.read(1024 * 1024)
                if not block:
                    break
                sha.update(block)

        self.finish_title.setText("ISO готов")
        self.finish_info.setText(
            f"Файл:\n{self.output_iso}\n\n"
            f"Размер: {human_size(self.output_iso.stat().st_size)}\n\n"
            f"SHA256-файл:\n{self.output_iso.with_suffix(self.output_iso.suffix + '.sha256')}"
        )
        self.finish_hash.setText(f"SHA256:\n{sha.hexdigest()}")

    def open_output_dir(self):
        if not self.output_iso:
            return
        path = self.output_iso.parent
        if command_exists("xdg-open"):
            subprocess.Popen(["xdg-open", str(path)])

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Операция выполняется",
                "Операция ещё выполняется. Закрыть Builder?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Sans", 10))
    window = Builder()
    window.show()
    sys.exit(app.exec())
