import sys
import os
import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QFrame)

# Import the sync engine tasks we built in the previous step
from sync_engine import check_internet, save_student_offline, sync_local_to_cloud, LOCAL_DB_PATH

class SchoolManagementDesktop(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FrancisTech School Management - Desktop Client")
        self.setMinimumSize(600, 450)
        
        # Ensure the local directory and database tables exist locally
        self.initialize_local_database()

        # UI Setup Layout
        self.init_ui()

        # Background Network Heartbeat Engine Timer (Runs every 5 seconds)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.network_heartbeat)
        self.sync_timer.start(5000) 
        
        # Run an initial check immediately on startup
        self.network_heartbeat()

    def init_ui(self):
        # Main layout container
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 1. Top Connection Bar Status
        self.status_frame = QFrame()
        self.status_frame.setFrameShape(QFrame.StyledPanel)
        status_layout = QHBoxLayout(self.status_frame)
        
        self.status_label = QLabel("Checking connection status...")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.status_label)
        layout.addWidget(self.status_frame)

        # 2. Input Fields Panel
        form_layout = QVBoxLayout()
        form_layout.addWidget(QLabel("Student Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter full legal name")
        form_layout.addWidget(self.name_input)

        form_layout.addWidget(QLabel("Assigned Grade / Class Level:"))
        self.grade_input = QLineEdit()
        self.grade_input.setPlaceholderText("e.g., Grade 10, Grade 11")
        form_layout.addWidget(self.grade_input)
        
        layout.addLayout(form_layout)

        # 3. Action Buttons Layout
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Record")
        self.save_btn.clicked.connect(self.handle_save)
        btn_layout.addWidget(self.save_btn)

        self.sync_btn = QPushButton("Force Manual Cloud Sync")
        self.sync_btn.clicked.connect(self.handle_manual_sync)
        btn_layout.addWidget(self.sync_btn)
        layout.addLayout(btn_layout)

        # 4. Logger Console Window Output
        layout.addWidget(QLabel("Local Application Event Activity Logs:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self.log_message("System initialized. Application window rendering finalized.")

    def log_message(self, text):
        """Helper to print logs directly inside the UI window console view"""
        self.log_output.append(text)

    def initialize_local_database(self):
        """Creates the local isolated sqlite configuration directory if missing"""
        os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                grade TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_synced INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def network_heartbeat(self):
        """Automated function checking internet availability and attempting data syncs"""
        is_online = check_internet()
        if is_online:
            self.status_label.setText("🟢 SYSTEM ONLINE — Connected to Central Cloud Database API")
            self.status_frame.setStyleSheet("background-color: #D4EDDA; color: #155724; font-weight: bold;")
            # Auto sync outstanding rows if we find a good network path
            sync_local_to_cloud()
        else:
            self.status_label.setText("🔴 SYSTEM OFFLINE — Operating safely in Isolated Local Cache Mode")
            self.status_frame.setStyleSheet("background-color: #F8D7DA; color: #721C24; font-weight: bold;")

    def handle_save(self):
        name = self.name_input.text().strip()
        grade = self.grade_input.text().strip()

        if not name or not grade:
            self.log_message("⚠️ Error: Input fields cannot be empty.")
            return

        # Save directly to the local SQLite system database layer
        save_student_offline(name, grade)
        self.log_message(f"💾 Local transaction saved successfully for: {name} ({grade})")
        
        # Clear form inputs
        self.name_input.clear()
        self.grade_input.clear()
        
        # Trigger an immediate synchronization attempt if online
        self.network_heartbeat()

    def handle_manual_sync(self):
        self.log_message("🔄 Force manual database synchronization started...")
        if check_internet():
            success = sync_local_to_cloud()
            if success:
                self.log_message("✅ Manual data sync sequence completed.")
        else:
            self.log_message("❌ Connection failed. Unable to synchronize with cloud architecture.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchoolManagementDesktop()
    window.show()
    sys.exit(app.exec())