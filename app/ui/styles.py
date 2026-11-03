
LIGHT = """
QMainWindow, QWidget#appRoot, QWidget#pageRoot, QWidget#scrollContent,
QStackedWidget, QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
    background:#F6F8FC;
    color:#182235;
}
QWidget { color:#182235; font-size:14px; }
QFrame { background:transparent; border:none; }
QLabel { background:transparent; }

QFrame#sidebar { background:#14243B; border:none; }
QFrame#sidebar QLabel { background:transparent; color:#DCE7F5; }
QLabel#brand { color:white; font-size:20px; font-weight:800; padding:4px 2px 0px 2px; }
QLabel#brandSub { color:#AFC2DA; font-size:11px; padding:0px 2px 10px 2px; }

QFrame#sideDateCard {
    background:#1D3453;
    border:1px solid #2B466A;
    border-radius:10px;
}
QFrame#sideDateCard QLabel {
    color:#F4F8FF;
    background:transparent;
}
QLabel#sideDateTitle { color:#C7D8EE; font-size:12px; }
QLabel#sideDateValue { color:#FFFFFF; font-size:14px; font-weight:700; }

QPushButton#nav {
    color:#DCE7F5; text-align:left; border:none; padding:10px 14px;
    border-radius:8px; background:transparent;
}
QPushButton#nav:hover { background:#203756; }
QPushButton#navActive {
    color:white; text-align:left; border:none; padding:10px 14px;
    border-radius:8px; background:#2F6FED; font-weight:600;
}

QFrame#card,QFrame#statCard,QFrame#projectCard,QFrame#hostMiniCard {
    background:#FFFFFF; border:1px solid #E2E8F2; border-radius:12px;
}
QLabel#muted { color:#778398; }
QLabel#sectionTitle { font-size:19px; font-weight:700; }
QLabel#bigNumber { font-size:28px; font-weight:800; }
QLabel#statLabel { font-size:13px; font-weight:650; color:#66758B; }
QLabel#statSub { font-size:12px; color:#8A96A8; }
QLabel#statValue { font-size:27px; font-weight:800; color:#182235; }
QFrame#pipelineCard,QFrame#pipelineStage { background:#FFFFFF; border:1px solid #E2E8F2; border-radius:12px; }
QLabel#stageTitle { font-size:14px; font-weight:700; color:#33415A; }
QLabel#stageCount { font-size:21px; font-weight:800; color:#182235; }
QLabel#stagePct { font-size:14px; font-weight:750; color:#2F6FED; }
QProgressBar#stageProgress { min-height:8px; max-height:8px; background:#E9EEF6; border-radius:4px; }
QProgressBar#stageProgress::chunk { background:#2F6FED; border-radius:4px; }
QProgressBar#overallProgress { min-height:12px; max-height:12px; background:#E9EEF6; border-radius:6px; }
QProgressBar#overallProgress::chunk { background:#2F6FED; border-radius:6px; }
QLabel#projectName { font-size:20px; font-weight:750; }
QLabel#accentText { color:#2F6FED; font-weight:650; }
QLabel#thumb { background:#EEF3F9; border:1px solid #E0E7F0; border-radius:8px; }

QProgressBar {
    background:#E9EEF6; border:none; border-radius:5px;
    min-height:9px; max-height:9px;
}
QProgressBar::chunk { background:#2F6FED; border-radius:5px; }

QLineEdit,QPlainTextEdit,QTextEdit,QSpinBox,QDateEdit {
    background:#FFFFFF; color:#182235; border:1px solid #D7DFEA;
    border-radius:8px; padding:8px;
    selection-background-color:#2F6FED; selection-color:white;
}
QComboBox {
    background:#FFFFFF; color:#182235; border:1px solid #D7DFEA;
    border-radius:8px; padding:8px 10px;
}

QPushButton {
    color:#25324A; background:#FFFFFF; border:1px solid #D7DFEA;
    border-radius:8px; padding:8px 12px;
}
QPushButton:hover { background:#F0F4FA; }
QPushButton#primaryBtn { background:#2F6FED; color:white; border:none; font-weight:650; }
QPushButton#dangerBtn { color:#C94646; background:#FFF7F7; border:1px solid #F1CFCF; }
QPushButton#themeBtn { min-width:42px; padding:6px 8px; }
QPushButton#themeBtn:checked { background:#2F6FED; color:white; border-color:#2F6FED; }

QTableWidget {
    background:#FFFFFF; alternate-background-color:#FBFCFE; color:#182235;
    border:1px solid #E2E8F2; border-radius:8px; gridline-color:#DCE3EC;
    selection-background-color:#DCE8FF; selection-color:#10213F;
}
QTableWidget::item { padding:6px; }
QHeaderView::section {
    background:#EEF3F9; color:#182235; border:none;
    border-right:1px solid #DCE3EC; border-bottom:1px solid #DCE3EC;
    padding:8px; font-weight:650;
}

QCalendarWidget QWidget { background:#FFFFFF; color:#182235; }
QCalendarWidget QToolButton {
    background:#FFFFFF; color:#182235; border:1px solid #D7DFEA;
    border-radius:8px; padding:8px; font-weight:650;
}
QCalendarWidget QSpinBox {
    background:#FFFFFF; color:#182235; border:1px solid #D7DFEA;
    border-radius:8px; padding:6px;
}
QCalendarWidget QAbstractItemView {
    background:#FFFFFF; color:#182235; selection-background-color:#2F6FED;
    selection-color:white; outline:0; font-size:15px;
}
QCalendarWidget QAbstractItemView:disabled { color:#AAB3C2; }

QScrollBar:vertical { background:#F0F3F8; width:11px; margin:0; }
QScrollBar::handle:vertical { background:#C5CFDC; min-height:24px; border-radius:5px; }
QScrollBar:horizontal { background:#F0F3F8; height:11px; margin:0; }
QScrollBar::handle:horizontal { background:#C5CFDC; min-width:24px; border-radius:5px; }

QDialog,QMessageBox { background:#F6F8FC; color:#182235; }
QMenu { background:#FFFFFF; color:#182235; border:1px solid #D7DFEA; }
QStatusBar { background:#FFFFFF; color:#778398; border-top:1px solid #E2E8F2; }

QTableCornerButton::section {
    background:#FFFFFF;
    border:1px solid #DCE3EC;
}
QCheckBox {
    spacing:7px;
    background:transparent;
}

QComboBox {
    min-height:40px;
    background:#FFFFFF;
    color:#182235;
    border:1px solid #D7DFEA;
    border-radius:10px;
    padding:0px 34px 0px 12px;
}
QComboBox:hover { border:1px solid #B8C5D8; background:#FBFCFE; }
QComboBox:focus { border:1px solid #2F6FED; }
QComboBox::drop-down { width:0px; border:none; }
QComboBox::down-arrow { image:none; width:0px; height:0px; }
QLabel#comboArrow { color:#778398; font-size:18px; background:transparent; }
QWidget#sheetColumnCell { background:transparent; }
QComboBox#sheetColumnCombo {
    min-height:26px; max-height:28px;
    padding:0 20px 0 8px; border-radius:6px;
}
QWidget#checkCell { background:transparent; }
QCheckBox#largeCheck::indicator {
    width:18px; height:18px;
    border:1px solid #B7C2D1;
    border-radius:5px;
    background:#FFFFFF;
}
QCheckBox#largeCheck::indicator:hover { border:1px solid #2F6FED; }
QCheckBox#largeCheck::indicator:checked {
    background:#2F6FED;
    border:1px solid #2F6FED;
}
QPushButton#fillHandle {
    border:none;
    border-radius:3px;
    padding:0px;
    min-width:4px; max-width:4px;
    min-height:4px; max-height:4px;
    background:#C7D9F8;
}
QPushButton#fillHandle:hover { background:#2F6FED; }
QPushButton#softBtn {
    min-height:38px;
    border-radius:10px;
    background:#F3F6FB;
    border:1px solid #D7DFEA;
}
"""

DARK = """
QMainWindow, QWidget#appRoot, QWidget#pageRoot, QWidget#scrollContent,
QStackedWidget, QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
    background:#151A22;
    color:#E8EDF5;
}
QWidget { color:#E8EDF5; font-size:14px; }
QFrame { background:transparent; border:none; }
QLabel { background:transparent; }

QFrame#sidebar { background:#0E1624; border:none; }
QFrame#sidebar QLabel { background:transparent; color:#CCD6E5; }
QLabel#brand { color:white; font-size:20px; font-weight:800; padding:4px 2px 0px 2px; }
QLabel#brandSub { color:#8FA4BF; font-size:11px; padding:0px 2px 10px 2px; }

QFrame#sideDateCard {
    background:#182638;
    border:1px solid #314258;
    border-radius:10px;
}
QFrame#sideDateCard QLabel {
    color:#F0F5FC;
    background:transparent;
}
QLabel#sideDateTitle { color:#A9B8CB; font-size:12px; }
QLabel#sideDateValue { color:#FFFFFF; font-size:14px; font-weight:700; }

QPushButton#nav {
    color:#CCD6E5; text-align:left; border:none; padding:10px 14px;
    border-radius:8px; background:transparent;
}
QPushButton#nav:hover { background:#1C2A40; }
QPushButton#navActive {
    color:white; text-align:left; border:none; padding:10px 14px;
    border-radius:8px; background:#2F6FED; font-weight:600;
}

QFrame#card,QFrame#statCard,QFrame#projectCard,QFrame#hostMiniCard {
    background:#1D242E; border:1px solid #34404E; border-radius:12px;
}
QLabel#muted { color:#9AA7BA; }
QLabel#sectionTitle { font-size:19px; font-weight:700; }
QLabel#bigNumber { font-size:28px; font-weight:800; }
QLabel#statLabel { font-size:13px; font-weight:650; color:#A9B8CB; }
QLabel#statSub { font-size:12px; color:#7F8CA0; }
QLabel#statValue { font-size:27px; font-weight:800; color:#F3F7FC; }
QFrame#pipelineCard,QFrame#pipelineStage { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QLabel#stageTitle { font-size:14px; font-weight:700; color:#D8E2EF; }
QLabel#stageCount { font-size:21px; font-weight:800; color:#F3F7FC; }
QLabel#stagePct { font-size:14px; font-weight:750; color:#6EA0FF; }
QProgressBar#stageProgress { min-height:8px; max-height:8px; background:#2A3442; border-radius:4px; }
QProgressBar#stageProgress::chunk { background:#6EA0FF; border-radius:4px; }
QLabel#projectName { font-size:20px; font-weight:750; }
QLabel#accentText { color:#6EA0FF; font-weight:650; }
QLabel#thumb { background:#252E3A; border:1px solid #34404E; border-radius:8px; }

QProgressBar {
    background:#2A3340; border:none; border-radius:5px;
    min-height:9px; max-height:9px;
}
QProgressBar::chunk { background:#4B82F1; border-radius:5px; }

QLineEdit,QPlainTextEdit,QTextEdit,QSpinBox,QDateEdit {
    background:#222A35; color:#F2F5F9; border:1px solid #3B4656;
    border-radius:8px; padding:8px;
    selection-background-color:#2F6FED; selection-color:white;
}
QComboBox {
    background:#222A35; color:#F2F5F9; border:1px solid #3B4656;
    border-radius:8px; padding:8px 10px;
}

QPushButton {
    color:#E8EDF5; background:#222A35; border:1px solid #3B4656;
    border-radius:8px; padding:8px 12px;
}
QPushButton:hover { background:#2A3442; }
QPushButton#primaryBtn { background:#2F6FED; color:white; border:none; font-weight:650; }
QPushButton#dangerBtn { color:#FF9A9A; background:#332326; border:1px solid #684047; }
QPushButton#themeBtn { min-width:42px; padding:6px 8px; }
QPushButton#themeBtn:checked { background:#4B82F1; color:white; border-color:#4B82F1; }

QTableWidget {
    background:#1D242E; alternate-background-color:#202833; color:#EDF2F8;
    border:1px solid #34404E; border-radius:8px; gridline-color:#303946;
    selection-background-color:#294C84; selection-color:white;
}
QTableWidget::item { padding:6px; }
QHeaderView::section {
    background:#252E3A; color:#F2F5F9; border:none;
    border-right:1px solid #3B4656; border-bottom:1px solid #3B4656;
    padding:8px; font-weight:650;
}

QCalendarWidget QWidget { background:#1D242E; color:#EDF2F8; }
QCalendarWidget QToolButton {
    background:#222A35; color:#F2F5F9; border:1px solid #3B4656;
    border-radius:8px; padding:8px; font-weight:650;
}
QCalendarWidget QSpinBox {
    background:#222A35; color:#F2F5F9; border:1px solid #3B4656;
    border-radius:8px; padding:6px;
}
QCalendarWidget QAbstractItemView {
    background:#1D242E; color:#EDF2F8; selection-background-color:#4B82F1;
    selection-color:white; outline:0; font-size:15px;
}
QCalendarWidget QAbstractItemView:disabled { color:#667386; }

QScrollBar:vertical { background:#1A2029; width:11px; margin:0; }
QScrollBar::handle:vertical { background:#465468; min-height:24px; border-radius:5px; }
QScrollBar:horizontal { background:#1A2029; height:11px; margin:0; }
QScrollBar::handle:horizontal { background:#465468; min-width:24px; border-radius:5px; }

QDialog,QMessageBox { background:#151A22; color:#E8EDF5; }
QMenu { background:#222A35; color:#E8EDF5; border:1px solid #3B4656; }
QStatusBar { background:#1D242E; color:#9AA7BA; border-top:1px solid #34404E; }

QTableCornerButton::section {
    background:#1D242E;
    border:1px solid #303946;
}
QCheckBox {
    spacing:7px;
    background:transparent;
}

QComboBox {
    min-height:40px;
    background:#222A35;
    color:#F2F5F9;
    border:1px solid #3B4656;
    border-radius:10px;
    padding:0px 34px 0px 12px;
}
QComboBox:hover { border:1px solid #566479; background:#27313E; }
QComboBox:focus { border:1px solid #4B82F1; }
QComboBox::drop-down { width:0px; border:none; }
QComboBox::down-arrow { image:none; width:0px; height:0px; }
QLabel#comboArrow { color:#9AA7BA; font-size:18px; background:transparent; }
QWidget#sheetColumnCell { background:transparent; }
QComboBox#sheetColumnCombo {
    min-height:26px; max-height:28px;
    padding:0 20px 0 8px; border-radius:6px;
}
QWidget#checkCell { background:transparent; }
QCheckBox#largeCheck::indicator {
    width:18px; height:18px;
    border:1px solid #5A687C;
    border-radius:5px;
    background:#222A35;
}
QCheckBox#largeCheck::indicator:hover { border:1px solid #6EA0FF; }
QCheckBox#largeCheck::indicator:checked {
    background:#4B82F1;
    border:1px solid #4B82F1;
}
QPushButton#fillHandle {
    border:none;
    border-radius:3px;
    padding:0px;
    min-width:4px; max-width:4px;
    min-height:4px; max-height:4px;
    background:#56779E;
}
QPushButton#fillHandle:hover { background:#6EA0FF; }
QPushButton#softBtn {
    min-height:38px;
    border-radius:10px;
    background:#252E3A;
    border:1px solid #3B4656;
}
"""

# V0.13.5.1 UI fidelity additions.  These are appended so the existing
# widget styles stay backward compatible while the redesigned pages can use
# a small, consistent component vocabulary.
LIGHT += r'''
QFrame#pageCard, QFrame#recipientCard, QFrame#hostCard, QFrame#channelCard,
QFrame#detailPanel, QFrame#compactCard, QFrame#deliveryRow, QFrame#queueCard {
    background:#FFFFFF; border:1px solid #E2E8F2; border-radius:14px;
}
QFrame#recipientCard[selected="true"], QFrame#hostCard[selected="true"] {
    border:2px solid #2F6FED; background:#F7FAFF;
}
QLabel#recipientInitial {
    background:#EAF1FF; color:#2F6FED; border-radius:28px;
    font-size:28px; font-weight:800; min-width:56px; min-height:56px;
    max-width:56px; max-height:56px;
}
QLabel#pageTitle { font-size:28px; font-weight:800; color:#172238; }
QLabel#pageSubtitle { color:#7B8799; font-size:13px; }
QLabel#cardTitle { font-size:16px; font-weight:750; color:#1C2940; }
QLabel#cardMeta { color:#7C889A; font-size:12px; }
QLabel#statusGood { color:#208B57; font-weight:700; }
QLabel#statusWarn { color:#C27B16; font-weight:700; }
QLabel#statusBad { color:#C84C4C; font-weight:700; }
QLabel#statusInfo { color:#2F6FED; font-weight:700; }
QLabel#compactMetric { color:#25324A; font-size:14px; font-weight:700; }
QPushButton#chipBtn {
    min-height:32px; padding:5px 12px; border-radius:16px;
    background:#F4F7FB; border:1px solid #DCE4EF; color:#4B596F;
}
QPushButton#chipBtn:checked { background:#E8F0FF; color:#2F6FED; border-color:#AFC6F6; }
QPushButton#cardButton { text-align:left; padding:10px 12px; border-radius:12px; }
QPushButton#ghostDanger { color:#B74848; background:transparent; border:1px solid #E8CACA; }
QFrame#topStrip { background:#F8FAFD; border:1px solid #E5EBF3; border-radius:12px; }
QScrollArea#cardScroll { border:none; background:transparent; }
QScrollArea#cardScroll QWidget#qt_scrollarea_viewport { background:transparent; }
'''

DARK += r'''
QFrame#pageCard, QFrame#recipientCard, QFrame#hostCard, QFrame#channelCard,
QFrame#detailPanel, QFrame#compactCard, QFrame#deliveryRow, QFrame#queueCard {
    background:#1D242E; border:1px solid #34404E; border-radius:14px;
}
QFrame#recipientCard[selected="true"], QFrame#hostCard[selected="true"] {
    border:2px solid #4B82F1; background:#202C3B;
}
QLabel#recipientInitial {
    background:#263A59; color:#8DB1FF; border-radius:28px;
    font-size:28px; font-weight:800; min-width:56px; min-height:56px;
    max-width:56px; max-height:56px;
}
QLabel#pageTitle { font-size:28px; font-weight:800; color:#F3F7FC; }
QLabel#pageSubtitle { color:#9AA7BA; font-size:13px; }
QLabel#cardTitle { font-size:16px; font-weight:750; color:#EEF3FA; }
QLabel#cardMeta { color:#9AA7BA; font-size:12px; }
QLabel#statusGood { color:#66D69A; font-weight:700; }
QLabel#statusWarn { color:#F0B45C; font-weight:700; }
QLabel#statusBad { color:#FF8D8D; font-weight:700; }
QLabel#statusInfo { color:#7EA7FF; font-weight:700; }
QLabel#compactMetric { color:#E8EDF5; font-size:14px; font-weight:700; }
QPushButton#chipBtn {
    min-height:32px; padding:5px 12px; border-radius:16px;
    background:#252E3A; border:1px solid #3B4656; color:#CBD5E3;
}
QPushButton#chipBtn:checked { background:#294C84; color:white; border-color:#4B82F1; }
QPushButton#cardButton { text-align:left; padding:10px 12px; border-radius:12px; }
QPushButton#ghostDanger { color:#FF9A9A; background:transparent; border:1px solid #684047; }
QFrame#topStrip { background:#1A212B; border:1px solid #303B49; border-radius:12px; }
QScrollArea#cardScroll { border:none; background:transparent; }
QScrollArea#cardScroll QWidget#qt_scrollarea_viewport { background:transparent; }
'''

# V0.13.5.12 workspace fidelity additions. UI-only; no business/data behavior.
LIGHT += r'''
QFrame#dashboardMetric {
    background:#FFFFFF; border:1px solid #E1E8F2; border-radius:13px;
}
QLabel#metricLabel { color:#637187; font-size:12px; font-weight:650; }
QLabel#metricValue { color:#182235; font-size:24px; font-weight:850; }
QLabel#metricValue[tone="info"] { color:#2F6FED; }
QLabel#metricValue[tone="good"] { color:#17945E; }
QLabel#metricValue[tone="warn"] { color:#CE841C; }
QLabel#metricValue[tone="bad"] { color:#D84D5B; }
QLabel#metricIcon { color:#2F6FED; font-size:20px; font-weight:800; min-width:28px; }
QLabel#metricIcon[tone="good"] { color:#17945E; }
QLabel#metricIcon[tone="warn"] { color:#CE841C; }
QLabel#metricIcon[tone="bad"] { color:#D84D5B; }

QPushButton#recipientSelect, QPushButton#recipientSelectActive {
    text-align:center; padding:8px; background:#FFFFFF; color:#23314A;
    border:1px solid #E0E7F1; border-radius:12px; font-weight:700;
}
QPushButton#recipientSelect:hover { background:#F7FAFF; border-color:#BFD1F2; }
QPushButton#recipientSelectActive { background:#F5F9FF; border:2px solid #2F6FED; color:#1E5FD6; }
QPushButton#hostSelect, QPushButton#hostSelectActive {
    text-align:left; padding:10px 12px; background:#FFFFFF; color:#22304A;
    border:1px solid #E0E7F1; border-radius:12px; font-weight:700;
}
QPushButton#hostSelect:hover { background:#F8FAFE; border-color:#BFD1F2; }
QPushButton#hostSelectActive { background:#F6FAFF; border:2px solid #2F6FED; }

QFrame#taskGroup { background:#F9FBFE; border:1px solid #E3EAF4; border-radius:12px; }
QFrame#taskRow { background:#FFFFFF; border:1px solid #E8EDF4; border-radius:10px; }
QPushButton#segmentBtn, QPushButton#segmentBtnDone, QPushButton#segmentBtnRedo, QPushButton#segmentBtnCurrent {
    padding:3px 7px; min-height:28px; border-radius:7px; background:#F4F7FB; border:1px solid #DDE5F0; color:#33415A; font-weight:700;
}
QPushButton#segmentBtnDone { background:#E9F8F0; border-color:#B8E3CA; color:#178656; }
QPushButton#segmentBtnRedo { background:#FFF1F1; border-color:#F2C7CC; color:#C84956; }
QPushButton#segmentBtnCurrent { background:#EAF2FF; border:2px solid #2F6FED; color:#1E5FD6; }
QPushButton#successAction { background:#23C987; color:#0C3527; border:none; font-weight:800; min-height:46px; }
QPushButton#dangerAction { background:#FF666B; color:#4B1114; border:none; font-weight:800; min-height:46px; }
QPushButton#reasonBtn { text-align:left; min-height:38px; background:#FFFFFF; border:1px solid #D9E2EE; }
QPushButton#reasonBtn:hover { background:#F2F7FF; border-color:#AFC6F6; }
QFrame#emptyState { background:#FBFCFE; border:1px dashed #CAD4E2; border-radius:14px; }
QWidget#videoHost { background:transparent; border:none; }
QFrame#stagePill { background:#F7F9FC; border:1px solid #E0E7F0; border-radius:10px; }
QLabel#stageSymbol { color:#2F6FED; font-size:20px; font-weight:850; }
QFrame#reviewRow, QFrame#workflowStep { background:#F8FAFD; border:1px solid #E4EAF3; border-radius:10px; }
QLabel#stepBadge { background:#EAF1FF; color:#2F6FED; min-width:30px; max-width:30px; min-height:30px; max-height:30px; border-radius:15px; font-weight:800; }
'''

DARK += r'''
QFrame#dashboardMetric {
    background:#1D242E; border:1px solid #34404E; border-radius:13px;
}
QLabel#metricLabel { color:#99A8BC; font-size:12px; font-weight:650; }
QLabel#metricValue { color:#F3F7FC; font-size:24px; font-weight:850; }
QLabel#metricValue[tone="info"] { color:#75A2FF; }
QLabel#metricValue[tone="good"] { color:#5DD79A; }
QLabel#metricValue[tone="warn"] { color:#F0B45C; }
QLabel#metricValue[tone="bad"] { color:#FF828E; }
QLabel#metricIcon { color:#75A2FF; font-size:20px; font-weight:800; min-width:28px; }
QLabel#metricIcon[tone="good"] { color:#5DD79A; }
QLabel#metricIcon[tone="warn"] { color:#F0B45C; }
QLabel#metricIcon[tone="bad"] { color:#FF828E; }
QPushButton#recipientSelect, QPushButton#recipientSelectActive {
    text-align:center; padding:8px; background:#1D242E; color:#E5ECF5;
    border:1px solid #34404E; border-radius:12px; font-weight:700;
}
QPushButton#recipientSelect:hover { background:#222C39; border-color:#52627A; }
QPushButton#recipientSelectActive { background:#20314C; border:2px solid #4B82F1; color:#9EBBFF; }
QPushButton#hostSelect, QPushButton#hostSelectActive {
    text-align:left; padding:10px 12px; background:#1D242E; color:#E5ECF5;
    border:1px solid #34404E; border-radius:12px; font-weight:700;
}
QPushButton#hostSelect:hover { background:#222C39; border-color:#52627A; }
QPushButton#hostSelectActive { background:#20314C; border:2px solid #4B82F1; }
QFrame#taskGroup { background:#1A212B; border:1px solid #303B49; border-radius:12px; }
QFrame#taskRow { background:#1D242E; border:1px solid #34404E; border-radius:10px; }
QPushButton#segmentBtn, QPushButton#segmentBtnDone, QPushButton#segmentBtnRedo, QPushButton#segmentBtnCurrent {
    padding:3px 7px; min-height:28px; border-radius:7px; background:#252E3A; border:1px solid #3B4656; color:#D8E2EF; font-weight:700;
}
QPushButton#segmentBtnDone { background:#183B2F; border-color:#2D654E; color:#70E0A6; }
QPushButton#segmentBtnRedo { background:#3A252B; border-color:#6C424A; color:#FF9AA5; }
QPushButton#segmentBtnCurrent { background:#243F6E; border:2px solid #4B82F1; color:#FFFFFF; }
QPushButton#successAction { background:#28D893; color:#082B20; border:none; font-weight:800; min-height:46px; }
QPushButton#dangerAction { background:#FF6F75; color:#3C0B0F; border:none; font-weight:800; min-height:46px; }
QPushButton#reasonBtn { text-align:left; min-height:38px; background:#222A35; border:1px solid #3B4656; }
QPushButton#reasonBtn:hover { background:#293646; border-color:#5A7499; }
QFrame#emptyState { background:#1A212B; border:1px dashed #465468; border-radius:14px; }
QWidget#videoHost { background:transparent; border:none; }
QFrame#stagePill { background:#202833; border:1px solid #34404E; border-radius:10px; }
QLabel#stageSymbol { color:#6EA0FF; font-size:20px; font-weight:850; }
QFrame#reviewRow, QFrame#workflowStep { background:#202833; border:1px solid #34404E; border-radius:10px; }
QLabel#stepBadge { background:#263A59; color:#8DB1FF; min-width:30px; max-width:30px; min-height:30px; max-height:30px; border-radius:15px; font-weight:800; }
'''

# V0.13.5.13 statistics dashboard redesign. UI-only.
LIGHT += r'''
QScrollArea#statsScroll { border:none; background:transparent; }
QScrollArea#statsScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#statsContent { background:transparent; }
QFrame#statsPanel {
    background:#FFFFFF; border:1px solid #E2E9F3; border-radius:14px;
}
QLabel#statsPanelTitle { color:#1C2A42; font-size:17px; font-weight:800; }
QLabel#rangeLabel { color:#5F6D82; background:#FFFFFF; border:1px solid #DCE4EF; border-radius:9px; padding:8px 12px; }
QFrame#funnelStage { background:#F8FAFE; border:1px solid #E4EAF3; border-radius:11px; }
QLabel#funnelLabel { color:#66758B; font-size:11px; font-weight:700; }
QLabel#funnelValue { color:#192842; font-size:20px; font-weight:850; }
QLabel#funnelPct { color:#2F6FED; font-size:11px; font-weight:750; }
QLabel#funnelArrow { color:#B7C4D6; font-size:26px; font-weight:700; min-width:12px; }
QFrame#statsListRow { background:#FBFCFE; border:1px solid #E8EDF4; border-radius:9px; }
QLabel#rankBadge { background:#EAF2FF; color:#2F6FED; border-radius:12px; font-weight:850; }
QLabel#goodText { color:#19945E; font-weight:750; }
QLabel#badText { color:#D84D5B; font-weight:750; }
QFrame#miniStatTile { background:#F8FAFD; border:1px solid #E3EAF3; border-radius:10px; }
QLabel#miniStatTitle { color:#66758B; font-size:11px; font-weight:700; }
QLabel#miniStatValue { color:#1C2A42; font-size:22px; font-weight:850; }
'''

DARK += r'''
QScrollArea#statsScroll { border:none; background:transparent; }
QScrollArea#statsScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#statsContent { background:transparent; }
QFrame#statsPanel {
    background:#1D242E; border:1px solid #34404E; border-radius:14px;
}
QLabel#statsPanelTitle { color:#F1F5FA; font-size:17px; font-weight:800; }
QLabel#rangeLabel { color:#A8B4C4; background:#222A35; border:1px solid #3B4656; border-radius:9px; padding:8px 12px; }
QFrame#funnelStage { background:#202833; border:1px solid #34404E; border-radius:11px; }
QLabel#funnelLabel { color:#9BA9BC; font-size:11px; font-weight:700; }
QLabel#funnelValue { color:#F4F7FB; font-size:20px; font-weight:850; }
QLabel#funnelPct { color:#7DA5FF; font-size:11px; font-weight:750; }
QLabel#funnelArrow { color:#5B687A; font-size:26px; font-weight:700; min-width:12px; }
QFrame#statsListRow { background:#202833; border:1px solid #34404E; border-radius:9px; }
QLabel#rankBadge { background:#263A59; color:#8DB1FF; border-radius:12px; font-weight:850; }
QLabel#goodText { color:#61D49A; font-weight:750; }
QLabel#badText { color:#FF8792; font-weight:750; }
QFrame#miniStatTile { background:#202833; border:1px solid #34404E; border-radius:10px; }
QLabel#miniStatTitle { color:#9BA9BC; font-size:11px; font-weight:700; }
QLabel#miniStatValue { color:#F4F7FB; font-size:22px; font-weight:850; }
'''

# V0.13.5.14 GPT prompt-center visual fidelity + responsive scrolling. UI only.
LIGHT += r'''
QScrollArea#promptPageScroll { border:none; background:transparent; }
QScrollArea#promptPageScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#promptPageContent { background:#F7F9FC; }
QFrame#workspacePanel { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:14px; }
QLabel#workspaceTitle { font-size:18px; font-weight:800; color:#1B2A44; }
QLabel#recipientInitialSmall { background:#EAF2FF; color:#2F6FED; border-radius:20px; min-width:40px; max-width:40px; min-height:40px; max-height:40px; font-size:19px; font-weight:850; }
QLabel#recipientName { color:#20304B; font-weight:800; font-size:14px; }
QLabel#hostName { color:#17243A; font-size:17px; font-weight:850; }
QLabel#hostThumb { background:#F0F3F8; border:1px solid #E0E7F1; border-radius:10px; }
QLabel#miniTag, QLabel#miniTagAlt { padding:2px 6px; border-radius:7px; font-size:11px; font-weight:700; }
QLabel#miniTag { background:#EAF2FF; color:#2F6FED; }
QLabel#miniTagAlt { background:#F2EAFE; color:#8057C7; }
QPushButton#filterChip, QPushButton#filterChipActive { min-height:28px; padding:3px 11px; border-radius:8px; font-weight:700; }
QPushButton#filterChip { background:#F5F7FB; border:1px solid #E1E7F0; color:#718098; }
QPushButton#filterChipActive { background:#2F6FED; border:1px solid #2F6FED; color:white; }
QPushButton#transparentHit { background:transparent; border:none; }
QFrame#recipientCard { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:12px; }
QFrame#recipientCard[selected="true"] { background:#F6FAFF; border:2px solid #2F6FED; }
QFrame#hostCard { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:13px; }
QFrame#hostCard[selected="true"] { background:#F8FBFF; border:2px solid #2F6FED; }
'''
DARK += r'''
QScrollArea#promptPageScroll { border:none; background:transparent; }
QScrollArea#promptPageScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#promptPageContent { background:#161C24; }
QFrame#workspacePanel { background:#1D242E; border:1px solid #34404E; border-radius:14px; }
QLabel#workspaceTitle { font-size:18px; font-weight:800; color:#F0F4FA; }
QLabel#recipientInitialSmall { background:#263A59; color:#8DB1FF; border-radius:20px; min-width:40px; max-width:40px; min-height:40px; max-height:40px; font-size:19px; font-weight:850; }
QLabel#recipientName { color:#EAF0F8; font-weight:800; font-size:14px; }
QLabel#hostName { color:#F2F6FB; font-size:17px; font-weight:850; }
QLabel#hostThumb { background:#252D38; border:1px solid #3C4858; border-radius:10px; }
QLabel#miniTag, QLabel#miniTagAlt { padding:2px 6px; border-radius:7px; font-size:11px; font-weight:700; }
QLabel#miniTag { background:#263A59; color:#8DB1FF; }
QLabel#miniTagAlt { background:#3A2F50; color:#C3A7FF; }
QPushButton#filterChip, QPushButton#filterChipActive { min-height:28px; padding:3px 11px; border-radius:8px; font-weight:700; }
QPushButton#filterChip { background:#252E3A; border:1px solid #3B4656; color:#AAB6C7; }
QPushButton#filterChipActive { background:#4B82F1; border:1px solid #4B82F1; color:white; }
QPushButton#transparentHit { background:transparent; border:none; }
QFrame#recipientCard { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QFrame#recipientCard[selected="true"] { background:#20314C; border:2px solid #4B82F1; }
QFrame#hostCard { background:#1D242E; border:1px solid #34404E; border-radius:13px; }
QFrame#hostCard[selected="true"] { background:#20314C; border:2px solid #4B82F1; }
'''

# V0.13.5.16 responsive viewport shell
LIGHT += r'''
QScrollArea#workflowPageScroll, QScrollArea#pageScroll { border:none; background:#F6F8FC; }
QScrollArea#workflowPageScroll QWidget#qt_scrollarea_viewport, QScrollArea#pageScroll QWidget#qt_scrollarea_viewport { background:#F6F8FC; }
QWidget#workflowPageContent, QWidget#pageScrollContent { background:#F6F8FC; }
'''
DARK += r'''
QScrollArea#workflowPageScroll, QScrollArea#pageScroll { border:none; background:#151A22; }
QScrollArea#workflowPageScroll QWidget#qt_scrollarea_viewport, QScrollArea#pageScroll QWidget#qt_scrollarea_viewport { background:#151A22; }
QWidget#workflowPageContent, QWidget#pageScrollContent { background:#151A22; }
'''

# V0.13.5.71 delivery-management reference layout. Flat UI only; no glass effects.
LIGHT += r'''
QFrame#deliveryDateBar {
    background:#FFFFFF; border:1px solid #DFE7F2; border-radius:12px;
}
QLabel#deliveryDateIcon {
    color:#2F6FED; background:#EAF2FF; border-radius:8px;
    min-width:30px; max-width:30px; min-height:30px; max-height:30px;
    font-size:16px; font-weight:800;
}
QLabel#deliveryDateCaption { color:#43516A; font-weight:700; }
QLabel#deliveryDateValue { color:#18305E; font-weight:800; font-size:15px; }
QPushButton#deliveryDateButton {
    background:#FFFFFF; border:1px solid #D7E0EC; color:#30415E;
    border-radius:9px; min-height:32px; padding:5px 11px; font-weight:700;
}
QPushButton#deliveryDateButton:hover { background:#F4F7FB; border-color:#B9C9DF; }

QFrame#deliveryMetric {
    background:#FFFFFF; border:1px solid #DFE7F2; border-radius:12px;
    min-height:66px;
}
QLabel#deliveryMetricIcon {
    min-width:38px; max-width:38px; min-height:38px; max-height:38px;
    border-radius:19px; background:#EAF2FF; color:#2F6FED;
    font-size:18px; font-weight:900;
}
QLabel#deliveryMetricIcon[tone="good"] { background:#E8F7EF; color:#16945C; }
QLabel#deliveryMetricIcon[tone="warn"] { background:#FFF2E4; color:#E27A12; }
QLabel#deliveryMetricIcon[tone="bad"] { background:#FFEAF0; color:#D8475D; }
QLabel#deliveryMetricValue { color:#176BDB; font-size:24px; font-weight:900; }
QLabel#deliveryMetricValue[tone="good"] { color:#15945D; }
QLabel#deliveryMetricValue[tone="warn"] { color:#E1700A; }
QLabel#deliveryMetricValue[tone="bad"] { color:#D83E58; }
QLabel#deliveryMetricLabel { color:#56657C; font-size:12px; font-weight:700; }

QPushButton#deliveryFilterBtn {
    background:#FFFFFF; color:#34445F; border:1px solid #DCE4EF;
    border-radius:9px; min-height:34px; padding:5px 13px; font-weight:700;
}
QPushButton#deliveryFilterBtn:hover { background:#F5F8FD; border-color:#BFD0E9; }
QPushButton#deliveryFilterBtn:checked {
    background:#2F7AF0; color:#FFFFFF; border-color:#2F7AF0;
}
QLineEdit#deliverySearch {
    min-height:34px; background:#FFFFFF; border:1px solid #DCE4EF;
    border-radius:9px; padding:0 12px;
}
QPushButton#deliveryIconButton, QPushButton#deliverySmallButton {
    background:#FFFFFF; color:#30415E; border:1px solid #DCE4EF;
    border-radius:9px; min-height:34px; padding:5px 11px; font-weight:650;
}
QPushButton#deliveryIconButton:hover, QPushButton#deliverySmallButton:hover { background:#F4F7FB; }
QPushButton#deliveryPrimaryBtn {
    background:#2F7AF0; color:#FFFFFF; border:none; border-radius:9px;
    min-height:36px; padding:6px 15px; font-weight:800;
}
QPushButton#deliveryPrimaryBtn:hover { background:#286DDA; }
QPushButton#deliveryPrimaryBtn:disabled { background:#B8C8E2; color:#F7FAFF; }

QFrame#deliveryListPanel, QFrame#deliveryDetailPanel {
    background:#FFFFFF; border:1px solid #DFE7F2; border-radius:13px;
}
QLabel#deliveryPanelTitle { color:#17263F; font-size:18px; font-weight:850; }
QLabel#deliverySortLabel { color:#738198; font-size:12px; font-weight:650; }
QScrollArea#deliveryDetailScroll { border:none; background:transparent; }
QScrollArea#deliveryDetailScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#deliveryListContent, QWidget#deliveryDetailContent { background:transparent; }

QFrame#deliveryRecipientCard {
    background:#FFFFFF; border:1px solid #E1E8F2; border-radius:12px;
}
QFrame#deliveryRecipientCard[selected="true"] {
    background:#F8FBFF; border:2px solid #2F7AF0;
}
QLabel#deliveryRecipientAvatar, QLabel#deliveryDetailAvatar {
    background:#EAF2FF; color:#246EDC; border-radius:24px;
    min-width:48px; max-width:48px; min-height:48px; max-height:48px;
    font-size:22px; font-weight:900;
}
QLabel#deliveryDetailAvatar { min-width:52px; max-width:52px; min-height:52px; max-height:52px; border-radius:26px; }
QLabel#deliveryRecipientName { color:#17263F; font-size:17px; font-weight:850; }
QLabel#deliveryDetailName { color:#17263F; font-size:21px; font-weight:900; }
QLabel#deliveryRecipientMeta { color:#76849A; font-size:12px; }
QLabel#deliveryCountStrong { color:#1A62C8; font-size:16px; font-weight:900; }
QLabel#deliveryPct { color:#40516C; font-size:12px; font-weight:800; }
QPushButton#deliveryMoreBtn {
    min-width:30px; max-width:30px; min-height:30px; max-height:30px;
    padding:0; background:#FFFFFF; color:#66758C; border:1px solid #DCE4EF; border-radius:8px;
}
QPushButton#deliveryLinkButton {
    background:transparent; border:none; color:#34506F; padding:3px 4px; font-weight:700;
}
QPushButton#deliveryLinkButton:hover { color:#2F6FED; }
QProgressBar#deliveryCardProgress, QProgressBar#deliveryOverallProgress, QProgressBar#deliveryTinyProgress {
    background:#E7EDF6; border:none; border-radius:5px; min-height:9px; max-height:9px;
}
QProgressBar#deliveryCardProgress::chunk, QProgressBar#deliveryOverallProgress::chunk, QProgressBar#deliveryTinyProgress::chunk {
    background:#2F7AF0; border-radius:5px;
}
QProgressBar#deliveryOverallProgress { min-height:11px; max-height:11px; border-radius:6px; }
QProgressBar#deliveryOverallProgress::chunk { border-radius:6px; }

QFrame#deliveryHostPill, QFrame#deliveryHostTile {
    background:#F7F9FC; border:1px solid #E2E8F1; border-radius:9px;
}
QFrame#deliveryHostPill[tone="good"], QFrame#deliveryHostTile[tone="good"] { background:#F1FBF6; border-color:#CAEAD9; }
QFrame#deliveryHostPill[tone="warn"], QFrame#deliveryHostTile[tone="warn"] { background:#FFF9F1; border-color:#F0DCC1; }
QFrame#deliveryHostPill[tone="info"], QFrame#deliveryHostTile[tone="info"] { background:#F3F8FF; border-color:#CFDFF5; }
QFrame#deliveryHostPill[tone="bad"], QFrame#deliveryHostTile[tone="bad"] { background:#FFF4F5; border-color:#F0CFD4; }
QLabel#deliveryHostIcon, QLabel#deliveryHostTileIcon {
    color:#E37A13; font-size:16px; font-weight:900;
}
QLabel#deliveryHostIcon[tone="good"], QLabel#deliveryHostTileIcon[tone="good"] { color:#15945D; }
QLabel#deliveryHostIcon[tone="info"], QLabel#deliveryHostTileIcon[tone="info"] { color:#2F7AF0; }
QLabel#deliveryHostIcon[tone="bad"], QLabel#deliveryHostTileIcon[tone="bad"] { color:#D7465B; }
QLabel#deliveryHostName { color:#2B3B55; font-size:12px; font-weight:800; }
QLabel#deliveryHostMeta { color:#6C7A90; font-size:11px; }
QLabel#deliveryWarning { color:#E34557; font-size:12px; font-weight:750; }
QLabel#deliveryInfoText { color:#2F6FED; font-size:12px; font-weight:750; }
QLabel#deliveryGoodText { color:#15945D; font-size:12px; font-weight:750; }

QFrame#deliveryProgressCard, QFrame#deliverySubCard {
    background:#FBFCFE; border:1px solid #E2E8F1; border-radius:11px;
}
QLabel#deliverySubTitle { color:#20314B; font-size:14px; font-weight:850; }
QLabel#deliverySmallLabel { color:#75839A; font-size:11px; font-weight:700; }
QLabel#deliveryPathText {
    color:#596980; background:#F3F6FA; border:1px solid #E3E8F0;
    border-radius:7px; padding:6px; font-size:11px;
}
QLabel#deliveryDriveIcon { color:#2F7AF0; font-size:20px; font-weight:900; }
QLabel#deliveryStatusBadge {
    min-width:64px; padding:6px 10px; border-radius:9px;
    background:#EDF4FF; color:#2F6FED; font-weight:800;
}
QLabel#deliveryStatusBadge[tone="good"] { background:#EAF8F0; color:#15945D; }
QLabel#deliveryStatusBadge[tone="warn"] { background:#FFF3E5; color:#D87514; }
QLabel#deliveryStatusBadge[tone="bad"] { background:#FFECEF; color:#D84358; }
QFrame#deliveryConfirmCard {
    background:#F0FBF5; border:1px solid #D3EFDE; border-radius:10px;
}
QLabel#deliveryConfirmText { color:#16834F; font-weight:800; }
QPushButton#deliveryGoodButton {
    background:#16A85F; color:#FFFFFF; border:none; border-radius:9px;
    min-height:40px; padding:7px 12px; font-size:15px; font-weight:850;
}
QPushButton#deliveryGoodButton:hover { background:#129553; }
QPushButton#deliveryGoodButton:disabled { background:#B9D8C7; color:#F5FAF7; }
QFrame#deliveryEmptyList, QFrame#deliveryEmptyDetail {
    background:#FBFCFE; border:1px dashed #D5DEEA; border-radius:11px;
}
QSplitter#deliverySplitter::handle { background:#F0F3F8; width:8px; }
'''

DARK += r'''
QFrame#deliveryDateBar { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QLabel#deliveryDateIcon { color:#8DB1FF; background:#263A59; border-radius:8px; min-width:30px; max-width:30px; min-height:30px; max-height:30px; font-size:16px; font-weight:800; }
QLabel#deliveryDateCaption { color:#B6C1D1; font-weight:700; }
QLabel#deliveryDateValue { color:#EAF1FB; font-weight:800; font-size:15px; }
QPushButton#deliveryDateButton { background:#222A35; border:1px solid #3B4656; color:#DDE5F0; border-radius:9px; min-height:32px; padding:5px 11px; font-weight:700; }
QPushButton#deliveryDateButton:hover { background:#2A3442; }

QFrame#deliveryMetric { background:#1D242E; border:1px solid #34404E; border-radius:12px; min-height:66px; }
QLabel#deliveryMetricIcon { min-width:38px; max-width:38px; min-height:38px; max-height:38px; border-radius:19px; background:#263A59; color:#8DB1FF; font-size:18px; font-weight:900; }
QLabel#deliveryMetricIcon[tone="good"] { background:#1F3B31; color:#66D69A; }
QLabel#deliveryMetricIcon[tone="warn"] { background:#3B3123; color:#F0B45C; }
QLabel#deliveryMetricIcon[tone="bad"] { background:#3C282E; color:#FF8792; }
QLabel#deliveryMetricValue { color:#82AAFF; font-size:24px; font-weight:900; }
QLabel#deliveryMetricValue[tone="good"] { color:#66D69A; }
QLabel#deliveryMetricValue[tone="warn"] { color:#F0B45C; }
QLabel#deliveryMetricValue[tone="bad"] { color:#FF8792; }
QLabel#deliveryMetricLabel { color:#A5B1C2; font-size:12px; font-weight:700; }

QPushButton#deliveryFilterBtn { background:#222A35; color:#C9D3E1; border:1px solid #3B4656; border-radius:9px; min-height:34px; padding:5px 13px; font-weight:700; }
QPushButton#deliveryFilterBtn:hover { background:#2A3442; }
QPushButton#deliveryFilterBtn:checked { background:#4B82F1; color:#FFFFFF; border-color:#4B82F1; }
QLineEdit#deliverySearch { min-height:34px; background:#222A35; border:1px solid #3B4656; border-radius:9px; padding:0 12px; }
QPushButton#deliveryIconButton, QPushButton#deliverySmallButton { background:#222A35; color:#D9E1EC; border:1px solid #3B4656; border-radius:9px; min-height:34px; padding:5px 11px; font-weight:650; }
QPushButton#deliveryIconButton:hover, QPushButton#deliverySmallButton:hover { background:#2A3442; }
QPushButton#deliveryPrimaryBtn { background:#4B82F1; color:#FFFFFF; border:none; border-radius:9px; min-height:36px; padding:6px 15px; font-weight:800; }
QPushButton#deliveryPrimaryBtn:hover { background:#3E75E4; }
QPushButton#deliveryPrimaryBtn:disabled { background:#3B4C68; color:#8997AB; }

QFrame#deliveryListPanel, QFrame#deliveryDetailPanel { background:#1D242E; border:1px solid #34404E; border-radius:13px; }
QLabel#deliveryPanelTitle { color:#F0F4FA; font-size:18px; font-weight:850; }
QLabel#deliverySortLabel { color:#9AA7BA; font-size:12px; font-weight:650; }
QScrollArea#deliveryDetailScroll { border:none; background:transparent; }
QScrollArea#deliveryDetailScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#deliveryListContent, QWidget#deliveryDetailContent { background:transparent; }

QFrame#deliveryRecipientCard { background:#202833; border:1px solid #34404E; border-radius:12px; }
QFrame#deliveryRecipientCard[selected="true"] { background:#20314C; border:2px solid #4B82F1; }
QLabel#deliveryRecipientAvatar, QLabel#deliveryDetailAvatar { background:#263A59; color:#8DB1FF; border-radius:24px; min-width:48px; max-width:48px; min-height:48px; max-height:48px; font-size:22px; font-weight:900; }
QLabel#deliveryDetailAvatar { min-width:52px; max-width:52px; min-height:52px; max-height:52px; border-radius:26px; }
QLabel#deliveryRecipientName { color:#F0F4FA; font-size:17px; font-weight:850; }
QLabel#deliveryDetailName { color:#F0F4FA; font-size:21px; font-weight:900; }
QLabel#deliveryRecipientMeta { color:#9AA7BA; font-size:12px; }
QLabel#deliveryCountStrong { color:#8DB1FF; font-size:16px; font-weight:900; }
QLabel#deliveryPct { color:#B7C2D2; font-size:12px; font-weight:800; }
QPushButton#deliveryMoreBtn { min-width:30px; max-width:30px; min-height:30px; max-height:30px; padding:0; background:#222A35; color:#AAB6C7; border:1px solid #3B4656; border-radius:8px; }
QPushButton#deliveryLinkButton { background:transparent; border:none; color:#AFC6F6; padding:3px 4px; font-weight:700; }
QPushButton#deliveryLinkButton:hover { color:#FFFFFF; }
QProgressBar#deliveryCardProgress, QProgressBar#deliveryOverallProgress, QProgressBar#deliveryTinyProgress { background:#2A3442; border:none; border-radius:5px; min-height:9px; max-height:9px; }
QProgressBar#deliveryCardProgress::chunk, QProgressBar#deliveryOverallProgress::chunk, QProgressBar#deliveryTinyProgress::chunk { background:#4B82F1; border-radius:5px; }
QProgressBar#deliveryOverallProgress { min-height:11px; max-height:11px; border-radius:6px; }
QProgressBar#deliveryOverallProgress::chunk { border-radius:6px; }

QFrame#deliveryHostPill, QFrame#deliveryHostTile { background:#252E3A; border:1px solid #3B4656; border-radius:9px; }
QFrame#deliveryHostPill[tone="good"], QFrame#deliveryHostTile[tone="good"] { background:#20352D; border-color:#35604B; }
QFrame#deliveryHostPill[tone="warn"], QFrame#deliveryHostTile[tone="warn"] { background:#362D22; border-color:#5B4930; }
QFrame#deliveryHostPill[tone="info"], QFrame#deliveryHostTile[tone="info"] { background:#24344C; border-color:#3E5680; }
QFrame#deliveryHostPill[tone="bad"], QFrame#deliveryHostTile[tone="bad"] { background:#39262C; border-color:#65414A; }
QLabel#deliveryHostIcon, QLabel#deliveryHostTileIcon { color:#F0B45C; font-size:16px; font-weight:900; }
QLabel#deliveryHostIcon[tone="good"], QLabel#deliveryHostTileIcon[tone="good"] { color:#66D69A; }
QLabel#deliveryHostIcon[tone="info"], QLabel#deliveryHostTileIcon[tone="info"] { color:#8DB1FF; }
QLabel#deliveryHostIcon[tone="bad"], QLabel#deliveryHostTileIcon[tone="bad"] { color:#FF8792; }
QLabel#deliveryHostName { color:#E5ECF5; font-size:12px; font-weight:800; }
QLabel#deliveryHostMeta { color:#9AA7BA; font-size:11px; }
QLabel#deliveryWarning { color:#FF8792; font-size:12px; font-weight:750; }
QLabel#deliveryInfoText { color:#8DB1FF; font-size:12px; font-weight:750; }
QLabel#deliveryGoodText { color:#66D69A; font-size:12px; font-weight:750; }

QFrame#deliveryProgressCard, QFrame#deliverySubCard { background:#202833; border:1px solid #34404E; border-radius:11px; }
QLabel#deliverySubTitle { color:#EDF2F8; font-size:14px; font-weight:850; }
QLabel#deliverySmallLabel { color:#9AA7BA; font-size:11px; font-weight:700; }
QLabel#deliveryPathText { color:#B8C3D2; background:#252E3A; border:1px solid #34404E; border-radius:7px; padding:6px; font-size:11px; }
QLabel#deliveryDriveIcon { color:#8DB1FF; font-size:20px; font-weight:900; }
QLabel#deliveryStatusBadge { min-width:64px; padding:6px 10px; border-radius:9px; background:#263A59; color:#8DB1FF; font-weight:800; }
QLabel#deliveryStatusBadge[tone="good"] { background:#20382F; color:#66D69A; }
QLabel#deliveryStatusBadge[tone="warn"] { background:#3B3123; color:#F0B45C; }
QLabel#deliveryStatusBadge[tone="bad"] { background:#3C282E; color:#FF8792; }
QFrame#deliveryConfirmCard { background:#20382F; border:1px solid #315945; border-radius:10px; }
QLabel#deliveryConfirmText { color:#66D69A; font-weight:800; }
QPushButton#deliveryGoodButton { background:#1DA866; color:#FFFFFF; border:none; border-radius:9px; min-height:40px; padding:7px 12px; font-size:15px; font-weight:850; }
QPushButton#deliveryGoodButton:hover { background:#179456; }
QPushButton#deliveryGoodButton:disabled { background:#335245; color:#7E9C8D; }
QFrame#deliveryEmptyList, QFrame#deliveryEmptyDetail { background:#202833; border:1px dashed #465468; border-radius:11px; }
QSplitter#deliverySplitter::handle { background:#171D26; width:8px; }
'''

# Statistics workspace: use the application theme, never the OS base palette.
LIGHT += r"""
QFrame#analyticsTabs, QFrame#analyticsMetric, QFrame#analyticsPanel, QFrame#analyticsChannelCard { background:#FFFFFF; border:1px solid #DFE7F2; border-radius:12px; }
QPushButton#analyticsTab { background:transparent; border:0; border-radius:8px; padding:9px 18px; color:#66758B; font-weight:700; }
QPushButton#analyticsTab:hover { background:#F0F5FC; color:#2F6FED; }
QPushButton#analyticsTab:checked { background:#2F6FED; color:#FFFFFF; }
QPushButton#analyticsRefresh { padding:8px 14px; border-radius:9px; }
QLabel#analyticsMetricLabel { color:#66758B; font-size:12px; font-weight:650; }
QLabel#analyticsMetricValue { color:#2F6FED; font-size:27px; font-weight:800; }
QLabel#analyticsMetricValue[tone="green"] { color:#16945C; }
QLabel#analyticsMetricValue[tone="orange"] { color:#C27B16; }
QLabel#analyticsMetricValue[tone="red"] { color:#D8475D; }
QLabel#analyticsMetricValue[tone="gray"] { color:#66758B; }
QLabel#analyticsMetricSub, QLabel#analyticsHint { color:#66758B; font-size:11px; }
QLabel#analyticsPanelTitle { color:#20304B; font-size:15px; font-weight:750; }
QLabel#analyticsDate { color:#66758B; font-weight:650; }
QWidget#analyticsChart { color:#66758B; background:transparent; }
QFrame#analyticsAlert { background:#FFF8EB; border:1px solid #C27B16; border-radius:8px; }
QFrame#analyticsGood { background:#F2FBF7; border:1px solid #DFE7F2; border-radius:8px; }
QFrame#analyticsBad { background:#FFF5F5; border:1px solid #D8475D; border-radius:8px; }
"""

# Statistics workspace: use the application theme, never the OS base palette.
DARK += r"""
QFrame#analyticsTabs, QFrame#analyticsMetric, QFrame#analyticsPanel, QFrame#analyticsChannelCard { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QPushButton#analyticsTab { background:transparent; border:0; border-radius:8px; padding:9px 18px; color:#A9B8CB; font-weight:700; }
QPushButton#analyticsTab:hover { background:#263A59; color:#8DB1FF; }
QPushButton#analyticsTab:checked { background:#4B82F1; color:#FFFFFF; }
QPushButton#analyticsRefresh { padding:8px 14px; border-radius:9px; }
QLabel#analyticsMetricLabel { color:#A9B8CB; font-size:12px; font-weight:650; }
QLabel#analyticsMetricValue { color:#8DB1FF; font-size:27px; font-weight:800; }
QLabel#analyticsMetricValue[tone="green"] { color:#66D69A; }
QLabel#analyticsMetricValue[tone="orange"] { color:#F0B45C; }
QLabel#analyticsMetricValue[tone="red"] { color:#FF8D8D; }
QLabel#analyticsMetricValue[tone="gray"] { color:#A9B8CB; }
QLabel#analyticsMetricSub, QLabel#analyticsHint { color:#A9B8CB; font-size:11px; }
QLabel#analyticsPanelTitle { color:#F0F4FA; font-size:15px; font-weight:750; }
QLabel#analyticsDate { color:#A9B8CB; font-weight:650; }
QWidget#analyticsChart { color:#A9B8CB; background:transparent; }
QFrame#analyticsAlert { background:#3C3020; border:1px solid #F0B45C; border-radius:8px; }
QFrame#analyticsGood { background:#20382F; border:1px solid #34404E; border-radius:8px; }
QFrame#analyticsBad { background:#402A31; border:1px solid #FF8D8D; border-radius:8px; }
"""

LIGHT += 'QWidget#analyticsContent { background:#F7F9FC; }'
DARK += 'QWidget#analyticsContent { background:#161C24; }'

LIGHT += 'QFrame#deliveryRecipientCard:hover, QFrame#deliveryRecipientCard:focus { border:1px solid #2F6FED; }'
DARK += 'QFrame#deliveryRecipientCard:hover, QFrame#deliveryRecipientCard:focus { border:1px solid #8DB1FF; }'

# Flow generation center production-progress cards: keep blank host areas theme-consistent.
# Scoped to this one monitor only; no production logic or other pages are affected.
LIGHT += r"""
QWidget#flowProductionProgressContent { background:#FFFFFF; }
QWidget#flowProductionProgressContent QFrame#compactCard,
QWidget#flowProductionProgressContent QFrame#hostCard { background:#FFFFFF; }
QWidget#flowProductionProgressContent QLabel#thumb { background:#EEF3F9; border:1px solid #E0E7F0; border-radius:8px; }
"""
DARK += r"""
QWidget#flowProductionProgressContent { background:#1D242E; }
QWidget#flowProductionProgressContent QFrame#compactCard,
QWidget#flowProductionProgressContent QFrame#hostCard { background:#1D242E; }
QWidget#flowProductionProgressContent QLabel#thumb { background:#252E3A; border:1px solid #34404E; border-radius:8px; }
"""

# Smooth recipient progress indicators replace text block glyphs.
LIGHT += r"""
QProgressBar#analyticsRecipientProgress { background:#EAF0F8; border:none; border-radius:4px; min-height:8px; max-height:8px; padding:0; }
QProgressBar#analyticsRecipientProgress::chunk { background:#397DF1; border:none; border-radius:4px; margin:0; }
QProgressBar#analyticsRecipientProgress[complete="true"]::chunk { background:#19A56B; }
"""
DARK += r"""
QProgressBar#analyticsRecipientProgress { background:#303E52; border:none; border-radius:4px; min-height:8px; max-height:8px; padding:0; }
QProgressBar#analyticsRecipientProgress::chunk { background:#79A5FF; border:none; border-radius:4px; margin:0; }
QProgressBar#analyticsRecipientProgress[complete="true"]::chunk { background:#59CE99; }
"""


# QC image replacement dialog: compact, readable and theme-consistent.  UI only.
LIGHT += r"""
QDialog#qcReplaceDialog { background:#F5F7FB; color:#182235; }
QFrame#qcReplaceHeader { background:#FFFFFF; border:1px solid #DDE6F1; border-radius:14px; }
QLabel#qcReplaceTitle { color:#14213A; font-size:22px; font-weight:850; }
QLabel#qcReplaceMeta { color:#53637B; font-size:14px; font-weight:750; }
QLabel#qcReplaceHint, QLabel#qcReplaceMiniHint { color:#738097; font-size:12px; }
QLabel#qcReplaceSafeBadge { background:#EEF5FF; color:#2F6FED; border:1px solid #CFE0FF; border-radius:9px; padding:5px 9px; font-size:11px; font-weight:800; }
QFrame#qcReplaceSection { background:#FFFFFF; border:1px solid #DEE6F0; border-radius:14px; }
QLabel#qcReplaceSectionTitle { color:#1C2940; font-size:15px; font-weight:850; }
QFrame#qcReplacePreviewCard, QFrame#qcReplaceTextCard, QFrame#qcReplacePromptCard { background:#FAFCFF; border:1px solid #E1E8F2; border-radius:11px; }
QLabel#qcReplaceCardTitle { color:#22304A; font-size:14px; font-weight:800; }
QLabel#qcReplaceSmallBadge { background:#F0F4FA; color:#66758B; border:1px solid #DFE6EF; border-radius:8px; padding:4px 7px; font-size:10px; font-weight:750; }
QLabel#qcReplaceImage { background:#F3F6FA; color:#6D7A90; border:1px dashed #CAD5E3; border-radius:9px; padding:6px; }
QLabel#qcReplaceImageStatus { color:#738097; font-size:11px; }
QLabel#qcReplaceImageStatus[tone="good"] { color:#178955; }
QLabel#qcReplaceImageStatus[tone="warn"] { color:#C27B16; }
QLabel#qcReplaceFieldLabel { color:#526078; font-size:11px; font-weight:800; }
QLineEdit#qcReplacePath { min-height:34px; background:#F8FAFD; border:1px solid #D9E2EE; border-radius:9px; padding:0 10px; color:#40506A; }
QPushButton#qcReplaceChooseButton { min-height:34px; border-radius:9px; padding:0 14px; font-weight:750; }
QPlainTextEdit#qcReplaceReadOnlyText { background:#F8FAFD; color:#3C4B63; border:1px solid #E0E7F0; border-radius:8px; padding:7px; font-size:12px; }
QLabel#qcReplaceStatus { border-radius:8px; padding:4px 8px; font-size:11px; font-weight:800; background:#F1F4F8; color:#718096; }
QLabel#qcReplaceStatus[tone="info"] { background:#EEF5FF; color:#2F6FED; }
QLabel#qcReplaceStatus[tone="good"] { background:#ECF8F1; color:#178955; }
QLabel#qcReplaceStatus[tone="bad"] { background:#FFF1F1; color:#C84C4C; }
QScrollArea#qcReplacePromptScroll, QWidget#qcReplacePromptViewport, QScrollArea#qcReplacePromptScroll QWidget#qt_scrollarea_viewport { background:transparent; border:none; }
QFrame#qcReplacePromptPlaceholder { background:#F8FAFD; border:1px dashed #D5DFEB; border-radius:10px; }
QLabel#qcReplaceSegmentBadge { min-width:62px; background:#EAF1FF; color:#2F6FED; border-radius:8px; padding:5px 8px; font-size:11px; font-weight:850; }
QLabel#qcReplacePromptSource { color:#68758A; font-size:11px; }
QPlainTextEdit#qcReplacePromptEditor { background:#FFFFFF; color:#182235; border:1px solid #CCD8E7; border-radius:9px; padding:8px; font-size:13px; selection-background-color:#2F6FED; selection-color:#FFFFFF; }
QPlainTextEdit#qcReplacePromptEditor:focus { border:1px solid #2F6FED; }
QPushButton#qcReplaceConfirm { min-height:38px; background:#2F6FED; color:white; border:none; border-radius:9px; padding:0 16px; font-weight:850; }
QPushButton#qcReplaceConfirm:hover { background:#245FD0; }
QPushButton#qcReplaceConfirm:disabled { background:#CBD5E3; color:#FFFFFF; }
"""

DARK += r"""
QDialog#qcReplaceDialog { background:#151B23; color:#E8EDF5; }
QFrame#qcReplaceHeader { background:#1D252F; border:1px solid #34404E; border-radius:14px; }
QLabel#qcReplaceTitle { color:#F2F6FB; font-size:22px; font-weight:850; }
QLabel#qcReplaceMeta { color:#B6C1D0; font-size:14px; font-weight:750; }
QLabel#qcReplaceHint, QLabel#qcReplaceMiniHint { color:#93A1B5; font-size:12px; }
QLabel#qcReplaceSafeBadge { background:#243B60; color:#8DB1FF; border:1px solid #355985; border-radius:9px; padding:5px 9px; font-size:11px; font-weight:800; }
QFrame#qcReplaceSection { background:#1D252F; border:1px solid #34404E; border-radius:14px; }
QLabel#qcReplaceSectionTitle { color:#F0F4FA; font-size:15px; font-weight:850; }
QFrame#qcReplacePreviewCard, QFrame#qcReplaceTextCard, QFrame#qcReplacePromptCard { background:#202833; border:1px solid #34404E; border-radius:11px; }
QLabel#qcReplaceCardTitle { color:#EEF3FA; font-size:14px; font-weight:800; }
QLabel#qcReplaceSmallBadge { background:#283240; color:#AAB6C8; border:1px solid #3A4656; border-radius:8px; padding:4px 7px; font-size:10px; font-weight:750; }
QLabel#qcReplaceImage { background:#171D25; color:#8E9BAE; border:1px dashed #435064; border-radius:9px; padding:6px; }
QLabel#qcReplaceImageStatus { color:#95A3B7; font-size:11px; }
QLabel#qcReplaceImageStatus[tone="good"] { color:#66D69A; }
QLabel#qcReplaceImageStatus[tone="warn"] { color:#F0B45C; }
QLabel#qcReplaceFieldLabel { color:#AAB6C8; font-size:11px; font-weight:800; }
QLineEdit#qcReplacePath { min-height:34px; background:#171D25; border:1px solid #3B4758; border-radius:9px; padding:0 10px; color:#D9E1EC; }
QPushButton#qcReplaceChooseButton { min-height:34px; border-radius:9px; padding:0 14px; font-weight:750; }
QPlainTextEdit#qcReplaceReadOnlyText { background:#171D25; color:#D7DFEA; border:1px solid #3A4656; border-radius:8px; padding:7px; font-size:12px; }
QLabel#qcReplaceStatus { border-radius:8px; padding:4px 8px; font-size:11px; font-weight:800; background:#283240; color:#AAB6C8; }
QLabel#qcReplaceStatus[tone="info"] { background:#243B60; color:#8DB1FF; }
QLabel#qcReplaceStatus[tone="good"] { background:#20382F; color:#66D69A; }
QLabel#qcReplaceStatus[tone="bad"] { background:#3C282E; color:#FF8D8D; }
QScrollArea#qcReplacePromptScroll, QWidget#qcReplacePromptViewport, QScrollArea#qcReplacePromptScroll QWidget#qt_scrollarea_viewport { background:transparent; border:none; }
QFrame#qcReplacePromptPlaceholder { background:#202833; border:1px dashed #465468; border-radius:10px; }
QLabel#qcReplaceSegmentBadge { min-width:62px; background:#263A59; color:#8DB1FF; border-radius:8px; padding:5px 8px; font-size:11px; font-weight:850; }
QLabel#qcReplacePromptSource { color:#9AA7BA; font-size:11px; }
QPlainTextEdit#qcReplacePromptEditor { background:#171D25; color:#F0F4FA; border:1px solid #465468; border-radius:9px; padding:8px; font-size:13px; selection-background-color:#4B82F1; selection-color:#FFFFFF; }
QPlainTextEdit#qcReplacePromptEditor:focus { border:1px solid #6EA0FF; }
QPushButton#qcReplaceConfirm { min-height:38px; background:#4B82F1; color:white; border:none; border-radius:9px; padding:0 16px; font-weight:850; }
QPushButton#qcReplaceConfirm:hover { background:#5B90F6; }
QPushButton#qcReplaceConfirm:disabled { background:#3A4656; color:#7F8CA0; }
"""


# Flow generation center: distinguish channel action buttons without changing business behavior.
LIGHT += r'''
QPushButton#channelAddNormalBtn { background:#EAF2FF; color:#245DB7; border:1px solid #B7CCF5; font-weight:750; }
QPushButton#channelAddNormalBtn:hover { background:#DCE9FF; border-color:#8FAFEA; }
QPushButton#channelRuntimeRetryBtn { background:#FFF3DF; color:#A7640F; border:1px solid #F0C98D; font-weight:750; }
QPushButton#channelRuntimeRetryBtn:hover { background:#FFE8C2; border-color:#E4AF5B; }
QPushButton#channelAddFastBtn { background:#F2ECFF; color:#7547B4; border:1px solid #D5C2F5; font-weight:750; }
QPushButton#channelAddFastBtn:hover { background:#E8DDFF; border-color:#BCA0EC; }
QPushButton#channelAddBrowserBtn { background:#EAF8F0; color:#237A4A; border:1px solid #B9DEC7; font-weight:750; }
QPushButton#channelAddBrowserBtn:hover { background:#DBF2E5; border-color:#91CBA8; }
'''
DARK += r'''
QPushButton#channelAddNormalBtn { background:#243A5C; color:#9CC0FF; border:1px solid #3E5F8A; font-weight:750; }
QPushButton#channelAddNormalBtn:hover { background:#2B466E; border-color:#577AA8; }
QPushButton#channelRuntimeRetryBtn { background:#463622; color:#F4C373; border:1px solid #70552F; font-weight:750; }
QPushButton#channelRuntimeRetryBtn:hover { background:#554127; border-color:#8B693A; }
QPushButton#channelAddFastBtn { background:#392E50; color:#CBB0FF; border:1px solid #594878; font-weight:750; }
QPushButton#channelAddFastBtn:hover { background:#45365F; border-color:#705B94; }
QPushButton#channelAddBrowserBtn { background:#233C31; color:#85D6AA; border:1px solid #395D4B; font-weight:750; }
QPushButton#channelAddBrowserBtn:hover { background:#29493A; border-color:#4E765F; }
'''

# Persona editor + fixed GPT workspace polish. UI-only.
# Keep every nested surface on the application theme instead of inheriting the
# operating-system/native light palette inside a dark window.
LIGHT += r'''
QDialog#personaDialog, QDialog#personaPresetDialog { background:#F6F8FC; color:#182235; }
QScrollArea#personaScroll, QScrollArea#personaPreviewScroll,
QScrollArea#personaScroll QWidget#qt_scrollarea_viewport,
QScrollArea#personaPreviewScroll QWidget#qt_scrollarea_viewport { background:#F6F8FC; border:none; }
QWidget#personaContent { background:#F6F8FC; }
QWidget#personaTabPage { background:#FFFFFF; color:#182235; }
QTabWidget#personaTabs::pane, QTabWidget#presetLibraryTabs::pane {
    background:#FFFFFF; border:1px solid #DCE4EF; border-radius:10px; top:-1px;
}
QTabWidget#personaTabs QTabBar::tab, QTabWidget#presetLibraryTabs QTabBar::tab {
    background:#EEF3F9; color:#526179; border:1px solid #D8E1EC;
    padding:9px 16px; min-height:28px; font-weight:700;
}
QTabWidget#personaTabs QTabBar::tab:selected, QTabWidget#presetLibraryTabs QTabBar::tab:selected {
    background:#FFFFFF; color:#1D2B43; border-bottom-color:#FFFFFF;
}
QTabWidget#personaTabs QTabBar::tab:hover, QTabWidget#presetLibraryTabs QTabBar::tab:hover { background:#F7FAFE; }
QDialog#personaPresetDialog QListWidget {
    background:#FFFFFF; color:#182235; border:1px solid #D7DFEA; border-radius:9px;
    selection-background-color:#E8F0FF; selection-color:#1E4FA8;
}
QPushButton#personaPoolChip {
    min-height:32px; padding:5px 12px; border-radius:12px;
    background:#F4F7FB; border:1px solid #DCE4EF; color:#5F6E84;
}
QPushButton#personaPoolChip:hover { background:#F8FBFF; border-color:#B7C5D8; }
QPushButton#personaPoolChip:checked { background:#E9F8F0; color:#157347; border:1px solid #25975B; font-weight:700; }
QLabel#personaPreviewLine { color:#7A8799; font-weight:650; }
QLabel#personaPreviewLine[allowed="true"] { color:#157347; font-weight:750; }
QPushButton#softBtn[successState="true"] {
    background:#DDF5E7; color:#157347; border:1px solid #25975B; font-weight:750;
}
QPushButton#softBtn[successState="true"]:hover { background:#CFEFDA; border-color:#1F8A50; }
QScrollArea#promptEditorScroll, QScrollArea#promptEditorScroll QWidget#qt_scrollarea_viewport,
QWidget#promptEditorContent { background:transparent; border:none; }
'''

DARK += r'''
QDialog#personaDialog, QDialog#personaPresetDialog { background:#151A22; color:#E8EDF5; }
QScrollArea#personaScroll, QScrollArea#personaPreviewScroll,
QScrollArea#personaScroll QWidget#qt_scrollarea_viewport,
QScrollArea#personaPreviewScroll QWidget#qt_scrollarea_viewport { background:#151A22; border:none; }
QWidget#personaContent { background:#151A22; }
QWidget#personaTabPage { background:#1D242E; color:#E8EDF5; }
QTabWidget#personaTabs::pane, QTabWidget#presetLibraryTabs::pane {
    background:#1D242E; border:1px solid #34404E; border-radius:10px; top:-1px;
}
QTabWidget#personaTabs QTabBar::tab, QTabWidget#presetLibraryTabs QTabBar::tab {
    background:#202833; color:#AAB6C7; border:1px solid #34404E;
    padding:9px 16px; min-height:28px; font-weight:700;
}
QTabWidget#personaTabs QTabBar::tab:selected, QTabWidget#presetLibraryTabs QTabBar::tab:selected {
    background:#1D242E; color:#F2F6FB; border-bottom-color:#1D242E;
}
QTabWidget#personaTabs QTabBar::tab:hover, QTabWidget#presetLibraryTabs QTabBar::tab:hover { background:#283342; }
QDialog#personaPresetDialog QListWidget {
    background:#1D242E; color:#EDF2F8; border:1px solid #3B4656; border-radius:9px;
    selection-background-color:#294C84; selection-color:#FFFFFF;
}
QPushButton#personaPoolChip {
    min-height:32px; padding:5px 12px; border-radius:12px;
    background:#252E3A; border:1px solid #3B4656; color:#C8D2E0;
}
QPushButton#personaPoolChip:hover { background:#2B3644; border-color:#52627A; }
QPushButton#personaPoolChip:checked { background:#183B2F; color:#70E0A6; border:1px solid #2D654E; font-weight:700; }
QLabel#personaPreviewLine { color:#8F9CAF; font-weight:650; }
QLabel#personaPreviewLine[allowed="true"] { color:#70E0A6; font-weight:750; }
QPushButton#softBtn[successState="true"] {
    background:#183B2F; color:#70E0A6; border:1px solid #2D654E; font-weight:750;
}
QPushButton#softBtn[successState="true"]:hover { background:#1F493A; border-color:#3A7A60; }
QScrollArea#promptEditorScroll, QScrollArea#promptEditorScroll QWidget#qt_scrollarea_viewport,
QWidget#promptEditorContent { background:transparent; border:none; }
'''

# Shared FRAME / MATERIAL toggle.  Theme-aware and wide enough for Chinese labels.
LIGHT += r'''
QPushButton#generationModeFrame, QPushButton#generationModeMaterial {
    min-height:30px; border-radius:7px; padding:4px 8px; font-weight:700;
    background:#FFFFFF; color:#667085; border:1px solid #D7DEE8;
}
QPushButton#generationModeFrame:hover, QPushButton#generationModeMaterial:hover { background:#F5F8FC; }
QPushButton#generationModeFrame:checked { background:#EAF2FF; color:#2F6FED; border-color:#2F6FED; }
QPushButton#generationModeMaterial:checked { background:#E9F8F0; color:#15945F; border-color:#15945F; }
QPushButton#qcOmniToggleBtn {
    min-height:30px; border-radius:7px; padding:4px 10px; font-weight:700;
    background:#FFFFFF; color:#667085; border:1px solid #D7DEE8;
}
QPushButton#qcOmniToggleBtn:hover { background:#F5F3FF; color:#6D28D9; border-color:#C4B5FD; }
QPushButton#qcOmniToggleBtn:checked {
    background:#7C3AED; color:#FFFFFF; border:1px solid #6D28D9; font-weight:800;
}
QPushButton#qcOmniToggleBtn:checked:hover { background:#6D28D9; border-color:#5B21B6; }
'''
DARK += r'''
QPushButton#generationModeFrame, QPushButton#generationModeMaterial {
    min-height:30px; border-radius:7px; padding:4px 8px; font-weight:700;
    background:#202833; color:#9AA7BA; border:1px solid #465468;
}
QPushButton#generationModeFrame:hover, QPushButton#generationModeMaterial:hover { background:#283442; }
QPushButton#generationModeFrame:checked { background:#243F6E; color:#9DBAFF; border-color:#4B82F1; }
QPushButton#generationModeMaterial:checked { background:#183B2F; color:#70E0A6; border-color:#2D654E; }
QPushButton#qcOmniToggleBtn {
    min-height:30px; border-radius:7px; padding:4px 10px; font-weight:700;
    background:#19202B; color:#8B9AB0; border:1px solid #334052;
}
QPushButton#qcOmniToggleBtn:hover { background:#28233B; color:#DDD6FE; border-color:#6D28D9; }
QPushButton#qcOmniToggleBtn:checked {
    background:#7C3AED; color:#FFFFFF; border:1px solid #8B5CF6; font-weight:800;
}
QPushButton#qcOmniToggleBtn:checked:hover { background:#6D28D9; border-color:#7C3AED; }
'''


# Persona camera-pool preview content must follow the active application theme.
# Kept as a final override so the inner QScrollArea widget cannot inherit a
# stale/native palette that disagrees with the surrounding persona panel.
LIGHT += r'''
QScrollArea#personaPreviewScroll,
QScrollArea#personaPreviewScroll QWidget#qt_scrollarea_viewport,
QWidget#personaPreviewContent {
    background:#FFFFFF; color:#182235; border:none;
}
'''
DARK += r'''
QScrollArea#personaPreviewScroll,
QScrollArea#personaPreviewScroll QWidget#qt_scrollarea_viewport,
QWidget#personaPreviewContent {
    background:#1D242E; color:#E8EDF5; border:none;
}
'''

# V0.13.5.92 Video Packaging page only. Scoped selectors keep all legacy pages untouched.
LIGHT += r'''
QTabWidget#packagingTabs::pane {
    background:#FFFFFF; border:1px solid #DCE4EF; border-radius:10px; top:-1px;
}
QTabWidget#packagingTabs QTabBar::tab {
    background:#EEF3F9; color:#526179; border:1px solid #D8E1EC;
    padding:8px 11px; min-height:27px; font-weight:700;
}
QTabWidget#packagingTabs QTabBar::tab:selected {
    background:#FFFFFF; color:#1D2B43; border-bottom-color:#FFFFFF;
}
QTabWidget#packagingTabs QTabBar::tab:hover { background:#F7FAFE; }
QListWidget#packagingTaskList {
    background:#FBFCFE; border:1px solid #E1E7F0; border-radius:10px; padding:5px;
}
QSplitter#packagingEditorSplitter::handle,
QSplitter#packagingVerticalSplitter::handle { background:#EEF2F7; }
QSplitter#packagingEditorSplitter::handle:hover,
QSplitter#packagingVerticalSplitter::handle:hover { background:#DCE7FA; }
'''

DARK += r'''
QTabWidget#packagingTabs::pane {
    background:#1D242E; border:1px solid #34404E; border-radius:10px; top:-1px;
}
QTabWidget#packagingTabs QTabBar::tab {
    background:#252E3A; color:#B9C5D5; border:1px solid #3B4656;
    padding:8px 11px; min-height:27px; font-weight:700;
}
QTabWidget#packagingTabs QTabBar::tab:selected {
    background:#1D242E; color:#EAF1FB; border-bottom-color:#1D242E;
}
QTabWidget#packagingTabs QTabBar::tab:hover { background:#2B3542; }
QListWidget#packagingTaskList {
    background:#202731; border:1px solid #34404E; border-radius:10px; padding:5px;
}
QSplitter#packagingEditorSplitter::handle,
QSplitter#packagingVerticalSplitter::handle { background:#303A47; }
QSplitter#packagingEditorSplitter::handle:hover,
QSplitter#packagingVerticalSplitter::handle:hover { background:#3A4B62; }
'''

# V0.13.5.95 Packaging workstation refinement. Scoped to packaging widgets only.
LIGHT += r'''
QTreeWidget#packagingTaskList {
    background:#FBFCFE; border:1px solid #E1E7F0; border-radius:10px; padding:5px;
    outline:none; show-decoration-selected:1;
}
QTreeWidget#packagingTaskList::item { min-height:30px; padding:2px 5px; border-radius:7px; }
QTreeWidget#packagingTaskList::item:selected { background:#E8F1FF; color:#1E63D5; }
QTreeWidget#packagingTaskList::item:hover { background:#F1F6FD; }
QTabWidget#packagingTabs QTableWidget { background:#FBFCFE; border:1px solid #E2E8F2; border-radius:8px; gridline-color:#EDF1F6; }
QTabWidget#packagingTabs QHeaderView::section { background:#F5F8FC; color:#5B687C; border:none; border-bottom:1px solid #E2E8F2; padding:6px; font-weight:700; }
QFrame#compactCard { background:#101419; }
'''
DARK += r'''
QTreeWidget#packagingTaskList {
    background:#202731; border:1px solid #34404E; border-radius:10px; padding:5px;
    outline:none; show-decoration-selected:1;
}
QTreeWidget#packagingTaskList::item { min-height:30px; padding:2px 5px; border-radius:7px; }
QTreeWidget#packagingTaskList::item:selected { background:#294C84; color:#FFFFFF; }
QTreeWidget#packagingTaskList::item:hover { background:#283341; }
QTabWidget#packagingTabs QTableWidget { background:#202731; border:1px solid #34404E; border-radius:8px; gridline-color:#303B49; }
QTabWidget#packagingTabs QHeaderView::section { background:#252E3A; color:#B9C5D5; border:none; border-bottom:1px solid #34404E; padding:6px; font-weight:700; }
QFrame#compactCard { background:#090B0E; }
'''

# V0.13.5.97 GPT Prompt Center tabs, enhancement tiers, B-roll presets, camera settings.
LIGHT += r'''
QTabWidget#promptCenterTabs::pane {
    background:#FFFFFF; border:1px solid #DCE4EF; border-radius:10px; top:-1px;
}
QTabWidget#promptCenterTabs QTabBar::tab {
    background:#EEF3F9; color:#526179; border:1px solid #D8E1EC;
    padding:9px 18px; min-height:28px; font-weight:700; font-size:14px;
}
QTabWidget#promptCenterTabs QTabBar::tab:selected {
    background:#FFFFFF; color:#1D2B43; border-bottom-color:#FFFFFF;
}
QTabWidget#promptCenterTabs QTabBar::tab:hover { background:#F7FAFE; }
QFrame#tierCard {
    background:#FFFFFF; border:1px solid #E2E8F2; border-radius:10px;
}
QFrame#tierCard[selected="true"] {
    background:#EEF5FF; border:2px solid #2F6FED;
}
QLabel#tierTitle { font-size:15px; font-weight:700; color:#1D2B43; }
QLabel#tierDesc { font-size:12px; color:#778398; }
QLabel#tierBadge {
    font-size:11px; font-weight:700; padding:3px 8px;
    border-radius:6px; background:#EDF2FA; color:#4A6B9A;
}
QLabel#tierBadge[tier="light"] { background:#E8F8ED; color:#1A7D42; }
QLabel#tierBadge[tier="standard"] { background:#EAF0FF; color:#2954A5; }
QLabel#tierBadge[tier="premium"] { background:#FFF5E5; color:#A06C1A; }
QFrame#brollPresetCard {
    background:#FFFFFF; border:1px solid #E2E8F2; border-radius:10px; padding:12px;
}
QFrame#brollPresetCard[selected="true"] {
    background:#EEF5FF; border:2px solid #2F6FED;
}
QFrame#brollPresetCard[disabled_preset="true"] { background:#F9FAFB; }
QLabel#brollPresetName { font-size:14px; font-weight:700; color:#1D2B43; }
QLabel#brollPresetDesc { font-size:12px; color:#778398; }
QLabel#brollDefaultBadge {
    font-size:10px; font-weight:700; padding:2px 6px;
    border-radius:4px; background:#E9F8F0; color:#157347;
}
QFrame#cameraSettingRow {
    background:#FFFFFF; border:1px solid #E9EEF5; border-radius:8px; padding:8px 12px;
}
QLabel#cameraSettingLabel { font-size:13px; font-weight:700; color:#33415A; }
QLabel#cameraSettingValue { font-size:13px; color:#5B6E86; }
QFrame#enhancementVideoCard {
    background:#FFFFFF; border:1px solid #E2E8F2; border-radius:8px;
}
QFrame#enhancementVideoCard[active="true"] {
    border:2px solid #2F6FED; background:#F6F9FF;
}
QLabel#previewSectionTitle { font-size:15px; font-weight:750; color:#1D2B43; }
QFrame#previewSegmentCard {
    background:#FFFFFF; border:1px solid #E9EEF5; border-radius:8px; padding:10px;
}
QPushButton#tierSelectBtn {
    background:#F4F7FB; color:#526179; border:1px solid #DCE4EF;
    border-radius:8px; padding:8px 14px; font-weight:700;
}
QPushButton#tierSelectBtn:hover { background:#EAF0F9; }
QPushButton#tierSelectBtn:checked, QPushButton#tierSelectBtn[selected="true"] {
    background:#2F6FED; color:white; border-color:#2F6FED;
}
'''

DARK += r'''
QTabWidget#promptCenterTabs::pane {
    background:#1D242E; border:1px solid #34404E; border-radius:10px; top:-1px;
}
QTabWidget#promptCenterTabs QTabBar::tab {
    background:#252E3A; color:#B9C5D5; border:1px solid #3B4656;
    padding:9px 18px; min-height:28px; font-weight:700; font-size:14px;
}
QTabWidget#promptCenterTabs QTabBar::tab:selected {
    background:#1D242E; color:#EAF1FB; border-bottom-color:#1D242E;
}
QTabWidget#promptCenterTabs QTabBar::tab:hover { background:#2B3542; }
QFrame#tierCard {
    background:#1D242E; border:1px solid #34404E; border-radius:10px;
}
QFrame#tierCard[selected="true"] {
    background:#1B2F4C; border:2px solid #4B82F1;
}
QLabel#tierTitle { font-size:15px; font-weight:700; color:#EAF1FB; }
QLabel#tierDesc { font-size:12px; color:#8F9CAF; }
QLabel#tierBadge {
    font-size:11px; font-weight:700; padding:3px 8px;
    border-radius:6px; background:#252E3A; color:#8FAACC;
}
QLabel#tierBadge[tier="light"] { background:#183B2F; color:#70E0A6; }
QLabel#tierBadge[tier="standard"] { background:#1B2F4C; color:#9DBAFF; }
QLabel#tierBadge[tier="premium"] { background:#3A3020; color:#F0C062; }
QFrame#brollPresetCard {
    background:#1D242E; border:1px solid #34404E; border-radius:10px; padding:12px;
}
QFrame#brollPresetCard[selected="true"] {
    background:#1B2F4C; border:2px solid #4B82F1;
}
QFrame#brollPresetCard[disabled_preset="true"] { background:#181D24; }
QLabel#brollPresetName { font-size:14px; font-weight:700; color:#EAF1FB; }
QLabel#brollPresetDesc { font-size:12px; color:#8F9CAF; }
QLabel#brollDefaultBadge {
    font-size:10px; font-weight:700; padding:2px 6px;
    border-radius:4px; background:#183B2F; color:#70E0A6;
}
QFrame#cameraSettingRow {
    background:#1D242E; border:1px solid #34404E; border-radius:8px; padding:8px 12px;
}
QLabel#cameraSettingLabel { font-size:13px; font-weight:700; color:#C8D2E0; }
QLabel#cameraSettingValue { font-size:13px; color:#8F9CAF; }
QFrame#enhancementVideoCard {
    background:#1D242E; border:1px solid #34404E; border-radius:8px;
}
QFrame#enhancementVideoCard[active="true"] {
    border:2px solid #4B82F1; background:#1B2F4C;
}
QLabel#previewSectionTitle { font-size:15px; font-weight:750; color:#EAF1FB; }
QFrame#previewSegmentCard {
    background:#1D242E; border:1px solid #34404E; border-radius:8px; padding:10px;
}
QPushButton#tierSelectBtn {
    background:#252E3A; color:#B9C5D5; border:1px solid #3B4656;
    border-radius:8px; padding:8px 14px; font-weight:700;
}
QPushButton#tierSelectBtn:hover { background:#2E3946; }
QPushButton#tierSelectBtn:checked, QPushButton#tierSelectBtn[selected="true"] {
    background:#2F6FED; color:white; border-color:#2F6FED;
}
'''


# Explicit control surfaces and palette keep OS dark mode from leaking into light UI.
from pathlib import Path as _ThemePath
_check_icon = (_ThemePath(__file__).resolve().parents[2] / 'assets/check-white.svg').as_posix()
_minus_icon = (_ThemePath(__file__).resolve().parents[2] / 'assets/minus-white.svg').as_posix()
for _dark in (False, True):
    _bg, _field, _fg, _muted, _border = ('#171E29','#232D3C','#EEF3FC','#B6C4D8','#62738A') if _dark else ('#F6F8FC','#FFFFFF','#182235','#526176','#AAB8CB')
    _extra = f"""
    QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{background:{_field};color:{_fg};border:1px solid {_border};selection-background-color:#2867D5;selection-color:white;}}
    QTabWidget::pane, QScrollArea > QWidget > QWidget {{background:{_bg};}}
    QTabBar::tab {{background:{_field};color:{_fg};padding:7px 10px;}}
    QTabBar::tab:selected, QPushButton#packagingSection:checked {{background:#2867D5;color:white;border:1px solid #72A5FF;}}
    QToolTip {{background:{_field};color:{_fg};border:1px solid {_border};padding:5px;}}
    QComboBox QAbstractItemView {{background:{_field};color:{_fg};selection-background-color:#2867D5;selection-color:white;}}
    QCheckBox::indicator, QTableView::indicator, QTreeView::indicator {{width:17px;height:17px;border:1px solid {_border};border-radius:3px;background:{_field};}}
    QCheckBox::indicator:checked, QCheckBox#largeCheck::indicator:checked, QTableView::indicator:checked, QTreeView::indicator:checked {{background:#2867D5;border:1px solid #2867D5;image:url("{_check_icon}");}}
    QCheckBox::indicator:indeterminate, QCheckBox#largeCheck::indicator:indeterminate {{background:#2867D5;border:1px solid #2867D5;image:url("{_minus_icon}");}}
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{background:#2867D5;color:white;}}
    QLabel#muted {{color:{_muted};}}
    QAbstractSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {{color:{_muted};background:{_bg};}}
    """
    if _dark: DARK += _extra
    else: LIGHT += _extra

def _base_style_is_fusion(app):
    style = app.style()
    seen = set()
    while style is not None and id(style) not in seen:
        seen.add(id(style))
        name = f"{style.objectName()} {style.metaObject().className()}".lower()
        if "fusion" in name:
            return True
        base = style.baseStyle() if hasattr(style, "baseStyle") else None
        style = base
    return False


def apply_control_palette(app, dark):
    from app.ui.control_guard import install_control_guard
    install_control_guard(app)
    from PySide6.QtGui import QPalette, QColor
    # setStyle('Fusion') restyles every widget. The app already uses Fusion after startup.
    if not _base_style_is_fusion(app):
        app.setStyle('Fusion')
    palette=QPalette()
    colors={'Window':'#171E29','Base':'#232D3C','AlternateBase':'#1D2633','Text':'#EEF3FC','WindowText':'#EEF3FC','Button':'#232D3C','ButtonText':'#EEF3FC','PlaceholderText':'#B6C4D8'} if dark else {'Window':'#F6F8FC','Base':'#FFFFFF','AlternateBase':'#EFF3F9','Text':'#182235','WindowText':'#182235','Button':'#FFFFFF','ButtonText':'#182235','PlaceholderText':'#526176'}
    colors.update(Highlight='#2867D5',HighlightedText='#FFFFFF',Link='#72A5FF' if dark else '#245ECB')
    for role,color in colors.items():palette.setColor(getattr(QPalette.ColorRole,role),QColor(color))
    app.setPalette(palette)

for _mode in ('light','dark'):
    _up=(_ThemePath(__file__).resolve().parents[2]/f'assets/spin-{_mode}-up.svg').as_posix()
    _down=(_ThemePath(__file__).resolve().parents[2]/f'assets/spin-{_mode}-down.svg').as_posix()
    _arrows=f'QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{image:url("{_up}");width:10px;height:9px;}} QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{image:url("{_down}");width:10px;height:9px;}}'
    if _mode=='dark':DARK+=_arrows
    else:LIGHT+=_arrows


# Task Center (任务中心) redesign: guide bar, metric chips, empty state, tool buttons.  UI only.
LIGHT += r'''
QFrame#tcGuide { background:#F8FAFD; border:1px solid #E3EAF3; border-radius:12px; }
QLabel#tcStep { padding:7px 15px; border-radius:15px; font-size:14px; font-weight:750; color:#7A879B; background:#EDF1F6; }
QLabel#tcStep[state="active"] { color:#FFFFFF; background:#2F6FED; }
QLabel#tcStep[state="done"] { color:#208B57; background:#E5F5EC; }
QLabel#tcArrow { color:#B4BECC; font-size:17px; font-weight:700; }
QLabel#tcGuideHint { color:#3E4B60; font-size:14px; }
QLabel#tcChip { padding:5px 12px; border-radius:12px; background:#EEF2F7; color:#3A475C; font-size:13px; font-weight:700; }
QLabel#tcChip[tone="good"] { background:#E5F5EC; color:#208B57; }
QLabel#tcChip[tone="warn"] { background:#FFF2DF; color:#B86E0C; }
QLabel#tcChip[tone="bad"] { background:#FDECEC; color:#C24848; }
QLabel#tcChip[tone="info"] { background:#E9F0FF; color:#2F6FED; }
QLabel#tcStatChip { padding:7px 16px; border-radius:16px; background:#EEF2F7; border:1px solid #DCE4EF; color:#1E2B42; font-size:15px; font-weight:800; }
QLabel#tcStatChip[tone="good"] { background:#E5F5EC; border:1px solid #B7E4C9; color:#187E4E; }
QLabel#tcStatChip[tone="warn"] { background:#FFF2DF; border:1px solid #F5D29B; color:#B46808; }
QLabel#tcStatChip[tone="bad"] { background:#FDECEC; border:1px solid #F3BFC2; color:#C24848; }
QLabel#tcStatChip[tone="info"] { background:#E9F0FF; border:1px solid #BFD3FA; color:#2F6FED; }
QLabel#tcSection { font-size:16px; font-weight:750; color:#1C2940; }
QLabel#tcHint { color:#8A96A8; font-size:12px; }
QLabel#tcTip { color:#4B596F; font-size:12px; background:#F4F7FC; border:1px solid #E3EAF3; border-radius:8px; padding:7px 9px; }
QFrame#tcEmpty { background:#FFFFFF; border:1px dashed #C9D4E3; border-radius:16px; }
QLabel#tcEmptyIcon { font-size:46px; }
QLabel#tcEmptyTitle { font-size:21px; font-weight:800; color:#1C2940; }
QFrame#tcDivider { background:#E5EBF3; min-height:1px; max-height:1px; border:none; }
QPushButton#warnBtn { background:#E8902A; color:white; border:none; font-weight:700; }
QPushButton#warnBtn:hover { background:#D9821F; }
QPushButton#primaryBtn:disabled, QPushButton#warnBtn:disabled { background:#B9C6DA; color:#F3F6FA; }
QPushButton#tcTool { text-align:left; padding:7px 10px; background:#F6F8FB; border:1px solid #E1E7F0; border-radius:8px; color:#33415A; }
QPushButton#tcTool:hover { border-color:#2F6FED; color:#2F6FED; }
QPushButton#tcTool:disabled { color:#AEB8C7; }
QFrame#hostCard:hover, QFrame#recipientCard:hover { border-color:#9DB8F2; }
QFrame#hostCard[selected="true"]:hover, QFrame#recipientCard[selected="true"]:hover { border-color:#2F6FED; }
'''

DARK += r'''
QFrame#tcGuide { background:#1A212B; border:1px solid #303B49; border-radius:12px; }
QLabel#tcStep { padding:7px 15px; border-radius:15px; font-size:14px; font-weight:750; color:#7F8CA0; background:#252E3A; }
QLabel#tcStep[state="active"] { color:#FFFFFF; background:#2F6FED; }
QLabel#tcStep[state="done"] { color:#66D69A; background:#1F3A2C; }
QLabel#tcArrow { color:#56637A; font-size:17px; font-weight:700; }
QLabel#tcGuideHint { color:#CBD5E3; font-size:14px; }
QLabel#tcChip { padding:5px 12px; border-radius:12px; background:#252E3A; color:#CBD5E3; font-size:13px; font-weight:700; }
QLabel#tcChip[tone="good"] { background:#1F3A2C; color:#66D69A; }
QLabel#tcChip[tone="warn"] { background:#3D2F1A; color:#F0B45C; }
QLabel#tcChip[tone="bad"] { background:#3D2326; color:#FF8D8D; }
QLabel#tcChip[tone="info"] { background:#20314C; color:#8DB1FF; }
QLabel#tcStatChip { padding:7px 16px; border-radius:16px; background:#252E3A; border:1px solid #384556; color:#E8EDF5; font-size:15px; font-weight:800; }
QLabel#tcStatChip[tone="good"] { background:#1F3A2C; border:1px solid #2D5A43; color:#66D69A; }
QLabel#tcStatChip[tone="warn"] { background:#3D2F1A; border:1px solid #5E4624; color:#F0B45C; }
QLabel#tcStatChip[tone="bad"] { background:#3D2326; border:1px solid #63343A; color:#FF8D8D; }
QLabel#tcStatChip[tone="info"] { background:#20314C; border:1px solid #35507D; color:#8DB1FF; }
QLabel#tcSection { font-size:16px; font-weight:750; color:#EEF3FA; }
QLabel#tcHint { color:#8593A8; font-size:12px; }
QLabel#tcTip { color:#B9C5D5; font-size:12px; background:#202833; border:1px solid #303B49; border-radius:8px; padding:7px 9px; }
QFrame#tcEmpty { background:#1D242E; border:1px dashed #3D4A5B; border-radius:16px; }
QLabel#tcEmptyIcon { font-size:46px; }
QLabel#tcEmptyTitle { font-size:21px; font-weight:800; color:#EEF3FA; }
QFrame#tcDivider { background:#303B49; min-height:1px; max-height:1px; border:none; }
QPushButton#warnBtn { background:#D9842A; color:white; border:none; font-weight:700; }
QPushButton#warnBtn:hover { background:#E8902A; }
QPushButton#primaryBtn:disabled, QPushButton#warnBtn:disabled { background:#34404E; color:#7F8CA0; }
QPushButton#tcTool { text-align:left; padding:7px 10px; background:#222A35; border:1px solid #34404E; border-radius:8px; color:#CBD5E3; }
QPushButton#tcTool:hover { border-color:#4B82F1; color:#8DB1FF; }
QPushButton#tcTool:disabled { color:#5E6B7E; }
QFrame#hostCard:hover, QFrame#recipientCard:hover { border-color:#4B6EA8; }
QFrame#hostCard[selected="true"]:hover, QFrame#recipientCard[selected="true"]:hover { border-color:#4B82F1; }
'''
# Task Center: card scroll areas sit inside white cards; never paint the page background in them.
LIGHT += 'QScrollArea#cardScroll > QWidget > QWidget#scrollContent { background:transparent; }'
DARK += 'QScrollArea#cardScroll > QWidget > QWidget#scrollContent { background:transparent; }'

# GPT Prompt Center (GPT 提示词中心) redesign: compact navigator, workflow bar, clean workspace. UI only.
LIGHT += r'''
QFrame#pcNavCard { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:12px; }
QFrame#pcActionBar { background:#FFFFFF; border:1px solid #E1E8F2; border-radius:12px; }
QFrame#pcActionBar QComboBox { min-height:28px; max-height:30px; padding:0px 22px 0px 8px; font-size:12.5px; border-radius:8px; }
QFrame#pcDividerV { background:#DFE6F0; min-width:1px; max-width:1px; min-height:22px; max-height:26px; border:none; }
QLabel#pcGroupLabel { color:#5B6B82; font-size:12px; font-weight:750; }
QLabel#pcFieldLabel { color:#23314A; font-size:13px; font-weight:750; }
QLabel#pcJobStatus { color:#3A4A63; font-size:12px; font-weight:650; background:#EFF4FB; border:1px solid #DCE5F2; border-radius:10px; padding:4px 10px; }
QLabel#pcEmptyNav { color:#5B6B82; font-size:13px; font-weight:600; padding:2px 6px; }
QPushButton#pcSubmitBtn { background:#16A34A; color:#FFFFFF; border:1px solid #15803D; border-radius:8px; font-weight:750; }
QPushButton#pcSubmitBtn:hover { background:#15803D; }
QPushButton#pcGenBtn { background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE; border-radius:8px; font-weight:750; }
QPushButton#pcGenBtn:hover { background:#DBEAFE; }
QLineEdit#pcSearchInput { background:#F8FAFC; border:1px solid #DCE4EF; border-radius:8px; padding:4px 10px; font-size:12px; color:#1E293B; }
QLineEdit#pcSearchInput:focus { background:#FFFFFF; border:1px solid #2F6FED; }
'''

DARK += r'''
QFrame#pcNavCard { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QFrame#pcActionBar { background:#1D242E; border:1px solid #34404E; border-radius:12px; }
QFrame#pcActionBar QComboBox { min-height:28px; max-height:30px; padding:0px 22px 0px 8px; font-size:12.5px; border-radius:8px; }
QFrame#pcDividerV { background:#34404E; min-width:1px; max-width:1px; min-height:22px; max-height:26px; border:none; }
QLabel#pcGroupLabel { color:#94A3B8; font-size:12px; font-weight:750; }
QLabel#pcFieldLabel { color:#E2E8F0; font-size:13px; font-weight:750; }
QLabel#pcJobStatus { color:#CBD5E1; font-size:12px; font-weight:650; background:#252E3A; border:1px solid #384556; border-radius:10px; padding:4px 10px; }
QLabel#pcEmptyNav { color:#94A3B8; font-size:13px; font-weight:600; padding:2px 6px; }
QPushButton#pcSubmitBtn { background:#15803D; color:#FFFFFF; border:1px solid #16A34A; border-radius:8px; font-weight:750; }
QPushButton#pcSubmitBtn:hover { background:#166534; }
QPushButton#pcGenBtn { background:#1E3A5F; color:#93C5FD; border:1px solid #2563EB; border-radius:8px; font-weight:750; }
QPushButton#pcGenBtn:hover { background:#1E40AF; }
QLineEdit#pcSearchInput { background:#222A35; border:1px solid #3B4656; border-radius:8px; padding:4px 10px; font-size:12px; color:#F1F5F9; }
QLineEdit#pcSearchInput:focus { background:#27313E; border:1px solid #4B82F1; }
'''

# GPT Prompt Center v3: 4-tier button hierarchy (L1 solid / L2 outline / L3 grey / L4 menus). UI only.
LIGHT += r'''
QPushButton#pcBtn { border-radius:9px; padding:0px 12px; font-size:13px; font-weight:700; }
QPushButton#pcBtn::menu-indicator { image:none; width:0px; }
QPushButton#pcBtn[tier="l1blue"] { background:#2563EB; color:#FFFFFF; border:1px solid #2563EB; font-size:14px; font-weight:800; }
QPushButton#pcBtn[tier="l1blue"]:hover { background:#1D4ED8; border-color:#1D4ED8; }
QPushButton#pcBtn[tier="l1green"] { background:#16A34A; color:#FFFFFF; border:1px solid #16A34A; font-size:14px; font-weight:800; }
QPushButton#pcBtn[tier="l1green"]:hover { background:#15803D; border-color:#15803D; }
QPushButton#pcBtn[tier="l2blue"] { background:#FFFFFF; color:#1D4ED8; border:1.5px solid #3B82F6; }
QPushButton#pcBtn[tier="l2blue"]:hover { background:#EFF6FF; }
QPushButton#pcBtn[tier="l2green"] { background:#FFFFFF; color:#15803D; border:1.5px solid #22C55E; }
QPushButton#pcBtn[tier="l2green"]:hover { background:#F0FDF4; }
QPushButton#pcBtn[tier="l2"] { background:#FFFFFF; color:#1E293B; border:1.5px solid #94A3B8; }
QPushButton#pcBtn[tier="l2"]:hover { background:#F1F5F9; border-color:#64748B; }
QPushButton#pcBtn[tier="l3"] { background:#F1F5F9; color:#334155; border:1px solid #F1F5F9; font-weight:650; }
QPushButton#pcBtn[tier="l3"]:hover { background:#E2E8F0; border-color:#E2E8F0; }
QPushButton#pcBtn[tier="l3on"] { background:#DBEAFE; color:#1D4ED8; border:1px solid #BFDBFE; }
QPushButton#pcBtn[tier="l3danger"] { background:#FFF1F2; color:#DC2626; border:1px solid #FECACA; font-weight:750; }
QPushButton#pcBtn[tier="l3danger"]:hover { background:#FEE2E2; border-color:#FCA5A5; }
QPushButton#pcBtn:disabled { background:#E2E8F0; color:#94A3B8; border-color:#E2E8F0; }
QPushButton#pcBtn[split="main"] { border-top-right-radius:0px; border-bottom-right-radius:0px; }
QPushButton#pcBtn[split="arrow"] { border-top-left-radius:0px; border-bottom-left-radius:0px; padding:0px; border-left:1px solid rgba(255,255,255,0.45); }
QPushButton#pcBtn[tier="l2blue"][split="arrow"] { border-left:1px solid #BFDBFE; }
QPushButton#pcBtn[tier="l2green"][split="arrow"] { border-left:1px solid #BBF7D0; }
QPushButton#pcSeg { padding:0px 14px; background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; font-size:13px; font-weight:650; }
QPushButton#pcSeg[pos="left"] { border-top-left-radius:9px; border-bottom-left-radius:9px; border-top-right-radius:0px; border-bottom-right-radius:0px; }
QPushButton#pcSeg[pos="right"] { border-top-right-radius:9px; border-bottom-right-radius:9px; border-top-left-radius:0px; border-bottom-left-radius:0px; }
QPushButton#pcSeg:hover { background:#E2E8F0; }
QPushButton#pcSeg:checked { background:#FFFFFF; color:#1D4ED8; border:1.5px solid #3B82F6; font-weight:800; }
QPushButton#pcLink { background:transparent; border:none; color:#64748B; padding:4px 6px; font-size:12.5px; text-decoration:underline; min-height:0px; }
QPushButton#pcLink:hover { color:#2563EB; background:transparent; }
QFrame#pcSelBar { background:#EFF6FF; border:1px solid #BFDBFE; border-radius:10px; }
QLabel#pcSelCount { color:#1D4ED8; font-size:13.5px; font-weight:800; }
QMenu, QMenu#pcMenu {
    background-color:#FFFFFF; color:#182235; border:1px solid #CFD9E6;
    border-radius:11px; padding:6px;
}
QMenu::item, QMenu#pcMenu::item {
    background-color:transparent; padding:8px 22px 8px 14px;
    border-radius:7px; font-size:13px; font-weight:600;
}
QMenu::item:selected, QMenu#pcMenu::item:selected { background-color:#EFF6FF; color:#1D4ED8; }
QMenu::item:disabled, QMenu#pcMenu::item:disabled { color:#94A3B8; background-color:transparent; }
QMenu::separator, QMenu#pcMenu::separator { height:1px; background:#E5ECF5; margin:5px 8px; }
QFrame#pcActionBar QComboBox { min-height:30px; max-height:34px; }
'''

DARK += r'''
QPushButton#pcBtn { border-radius:9px; padding:0px 12px; font-size:13px; font-weight:700; }
QPushButton#pcBtn::menu-indicator { image:none; width:0px; }
QPushButton#pcBtn[tier="l1blue"] { background:#2563EB; color:#FFFFFF; border:1px solid #2563EB; font-size:14px; font-weight:800; }
QPushButton#pcBtn[tier="l1blue"]:hover { background:#3B82F6; border-color:#3B82F6; }
QPushButton#pcBtn[tier="l1green"] { background:#16A34A; color:#FFFFFF; border:1px solid #16A34A; font-size:14px; font-weight:800; }
QPushButton#pcBtn[tier="l1green"]:hover { background:#22C55E; border-color:#22C55E; }
QPushButton#pcBtn[tier="l2blue"] { background:#1D242E; color:#93C5FD; border:1.5px solid #3B82F6; }
QPushButton#pcBtn[tier="l2blue"]:hover { background:#1E3A5F; }
QPushButton#pcBtn[tier="l2green"] { background:#1D242E; color:#86EFAC; border:1.5px solid #22C55E; }
QPushButton#pcBtn[tier="l2green"]:hover { background:#14532D; }
QPushButton#pcBtn[tier="l2"] { background:#1D242E; color:#E2E8F0; border:1.5px solid #64748B; }
QPushButton#pcBtn[tier="l2"]:hover { background:#27313E; }
QPushButton#pcBtn[tier="l3"] { background:#252E3A; color:#CBD5E1; border:1px solid #252E3A; font-weight:650; }
QPushButton#pcBtn[tier="l3"]:hover { background:#2F3A48; border-color:#2F3A48; }
QPushButton#pcBtn[tier="l3on"] { background:#1E3A5F; color:#93C5FD; border:1px solid #2563EB; }
QPushButton#pcBtn[tier="l3danger"] { background:#351F24; color:#FCA5A5; border:1px solid #7F1D1D; font-weight:750; }
QPushButton#pcBtn[tier="l3danger"]:hover { background:#4C1D24; border-color:#DC2626; }
QPushButton#pcBtn:disabled { background:#252E3A; color:#5E6B7E; border-color:#252E3A; }
QPushButton#pcBtn[split="main"] { border-top-right-radius:0px; border-bottom-right-radius:0px; }
QPushButton#pcBtn[split="arrow"] { border-top-left-radius:0px; border-bottom-left-radius:0px; padding:0px; border-left:1px solid rgba(255,255,255,0.35); }
QPushButton#pcSeg { padding:0px 14px; background:#252E3A; color:#AAB6C7; border:1px solid #34404E; font-size:13px; font-weight:650; }
QPushButton#pcSeg[pos="left"] { border-top-left-radius:9px; border-bottom-left-radius:9px; border-top-right-radius:0px; border-bottom-right-radius:0px; }
QPushButton#pcSeg[pos="right"] { border-top-right-radius:9px; border-bottom-right-radius:9px; border-top-left-radius:0px; border-bottom-left-radius:0px; }
QPushButton#pcSeg:hover { background:#2F3A48; }
QPushButton#pcSeg:checked { background:#1D242E; color:#93C5FD; border:1.5px solid #3B82F6; font-weight:800; }
QPushButton#pcLink { background:transparent; border:none; color:#94A3B8; padding:4px 6px; font-size:12.5px; text-decoration:underline; min-height:0px; }
QPushButton#pcLink:hover { color:#93C5FD; background:transparent; }
QFrame#pcSelBar { background:#1E3A5F; border:1px solid #2563EB; border-radius:10px; }
QLabel#pcSelCount { color:#BFDBFE; font-size:13.5px; font-weight:800; }
QMenu, QMenu#pcMenu {
    background-color:#1E2631; color:#E8EDF5; border:1px solid #3B4758;
    border-radius:11px; padding:6px;
}
QMenu::item, QMenu#pcMenu::item {
    background-color:transparent; padding:8px 22px 8px 14px;
    border-radius:7px; font-size:13px; font-weight:600;
}
QMenu::item:selected, QMenu#pcMenu::item:selected { background-color:#1E3A5F; color:#BFDBFE; }
QMenu::item:disabled, QMenu#pcMenu::item:disabled { color:#5E6B7E; background-color:transparent; }
QMenu::separator, QMenu#pcMenu::separator { height:1px; background:#323E4F; margin:5px 8px; }
QFrame#pcActionBar QComboBox { min-height:30px; max-height:34px; }
'''
LIGHT += 'QPushButton#pcBtn[compact="true"] { padding:0px; font-size:12px; }'
DARK += 'QPushButton#pcBtn[compact="true"] { padding:0px; font-size:12px; }'
# Mini FRAME / MATERIAL toggle for dense tables (GPT prompt center).
LIGHT += 'QPushButton#generationModeFrame[mini="true"], QPushButton#generationModeMaterial[mini="true"] { min-height:0px; padding:0px 2px; font-size:12px; border-radius:6px; }'
DARK += 'QPushButton#generationModeFrame[mini="true"], QPushButton#generationModeMaterial[mini="true"] { min-height:0px; padding:0px 2px; font-size:12px; border-radius:6px; }'

# GPT Prompt Center v4: inline 睁眼/闭眼 toggle + scope chip. UI only.
LIGHT += r'''
QPushButton#eyeTypeOpen, QPushButton#eyeTypeClosed { min-height:0px; padding:0px 2px; font-size:12px; font-weight:700; border-radius:6px; background:#FFFFFF; color:#667085; border:1px solid #D7DEE8; }
QPushButton#eyeTypeOpen:hover, QPushButton#eyeTypeClosed:hover { background:#F5F8FC; }
QPushButton#eyeTypeOpen:checked { background:#EAF2FF; color:#2F6FED; border-color:#2F6FED; }
QPushButton#eyeTypeClosed:checked { background:#F2EAFE; color:#7E3FCF; border-color:#8B5CF6; }
QLabel#pcScope { color:#475569; font-size:12.5px; font-weight:650; background:#F1F5F9; border-radius:10px; padding:5px 10px; }
QLabel#pcScope[active="true"] { color:#1D4ED8; background:#EFF6FF; border:1px solid #BFDBFE; font-weight:800; }
'''
DARK += r'''
QPushButton#eyeTypeOpen, QPushButton#eyeTypeClosed { min-height:0px; padding:0px 2px; font-size:12px; font-weight:700; border-radius:6px; background:#202833; color:#9AA7BA; border:1px solid #465468; }
QPushButton#eyeTypeOpen:hover, QPushButton#eyeTypeClosed:hover { background:#283442; }
QPushButton#eyeTypeOpen:checked { background:#243F6E; color:#9DBAFF; border-color:#4B82F1; }
QPushButton#eyeTypeClosed:checked { background:#3A2F50; color:#C3A7FF; border-color:#8B5CF6; }
QLabel#pcScope { color:#CBD5E1; font-size:12.5px; font-weight:650; background:#252E3A; border-radius:10px; padding:5px 10px; }
QLabel#pcScope[active="true"] { color:#BFDBFE; background:#1E3A5F; border:1px solid #2563EB; font-weight:800; }
'''

# Auto-Edit Center (DaVinciPage) v2: ASR capsule, unified stat pills, model settings cards. UI only.
LIGHT += r'''
QLabel#dvStatChip {
    padding:5px 12px; border-radius:13px; background:#EEF2F7; border:1px solid #DCE4EF;
    color:#1E2B42; font-size:13px; font-weight:750;
}
QLabel#dvStatChip[tone="good"] { background:#E5F5EC; border:1px solid #B7E4C9; color:#187E4E; }
QLabel#dvStatChip[tone="warn"] { background:#FFF2DF; border:1px solid #F5D29B; color:#B46808; }
QLabel#dvStatChip[tone="bad"] { background:#FDECEC; border:1px solid #F3BFC2; color:#C24848; }
QLabel#dvStatChip[tone="info"] { background:#E9F0FF; border:1px solid #BFD3FA; color:#2F6FED; }
QPushButton#asrCapsuleBtn {
    background:#EEF2FF; color:#3730A3; border:1px solid #C7D2FE;
    border-radius:13px; padding:5px 14px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#asrCapsuleBtn:hover { background:#E0E7FF; border-color:#818CF8; }
QPushButton#aiWmCapsuleBtn {
    background:#F1F5F9; color:#334155; border:1px solid #CBD5E1;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#aiWmCapsuleBtn:hover { background:#E2E8F0; border-color:#94A3B8; }
QPushButton#aiWmCapsuleBtn[active="true"] {
    background:#ECFEFF; color:#0E7490; border:1px solid #A5F3FC;
}
QPushButton#aiWmCapsuleBtn[active="true"]:hover { background:#CFFAFE; border-color:#22D3EE; }
QComboBox#dvTimelineCombo {
    background:#F8FAFC; color:#1E293B; border:1.5px solid #CBD5E1;
    border-radius:9px; padding:0px 10px; font-size:12.5px; font-weight:750; min-height:34px;
}
QComboBox#dvTimelineCombo:hover { border-color:#64748B; background:#F1F5F9; }
QPushButton#statDoneBtn {
    background:#E8F8F0; color:#14804A; border:1px solid #BDE8D1;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statDoneBtn:hover { background:#D1F2E1; border-color:#86EFAC; }
QFrame#asrModelCard {
    background:#F8FAFC; border:1.5px solid #E2E8F0; border-radius:11px;
}
QFrame#asrModelCard[selected="true"] {
    background:#EFF6FF; border:2px solid #2563EB;
}
'''
DARK += r'''
QLabel#dvStatChip {
    padding:5px 12px; border-radius:13px; background:#252E3A; border:1px solid #384556;
    color:#E8EDF5; font-size:13px; font-weight:750;
}
QLabel#dvStatChip[tone="good"] { background:#1F3A2C; border:1px solid #2D5A43; color:#66D69A; }
QLabel#dvStatChip[tone="warn"] { background:#3D2F1A; border:1px solid #5E4624; color:#F0B45C; }
QLabel#dvStatChip[tone="bad"] { background:#3D2326; border:1px solid #63343A; color:#FF8D8D; }
QLabel#dvStatChip[tone="info"] { background:#20314C; border:1px solid #35507D; color:#8DB1FF; }
QPushButton#asrCapsuleBtn {
    background:#262B44; color:#A5B4FC; border:1px solid #4338CA;
    border-radius:13px; padding:5px 14px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#asrCapsuleBtn:hover { background:#312E81; border-color:#6366F1; }
QPushButton#aiWmCapsuleBtn {
    background:#252E3A; color:#CBD5E1; border:1px solid #384556;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#aiWmCapsuleBtn:hover { background:#303D50; border-color:#4B5E78; }
QPushButton#aiWmCapsuleBtn[active="true"] {
    background:#13323B; color:#67E8F9; border:1px solid #0891B2;
}
QPushButton#aiWmCapsuleBtn[active="true"]:hover { background:#164E63; border-color:#22D3EE; }
QComboBox#dvTimelineCombo {
    background:#1D242E; color:#E2E8F0; border:1.5px solid #475569;
    border-radius:9px; padding:0px 10px; font-size:12.5px; font-weight:750; min-height:34px;
}
QComboBox#dvTimelineCombo:hover { border-color:#64748B; background:#252E3A; }
QPushButton#statDoneBtn {
    background:#1E382D; color:#7CE2B1; border:1px solid #2A5442;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statDoneBtn:hover { background:#14532D; border-color:#22C55E; }
QFrame#asrModelCard {
    background:#1D242E; border:1.5px solid #34404E; border-radius:11px;
}
QFrame#asrModelCard[selected="true"] {
    background:#1E3A5F; border:2px solid #3B82F6;
}
'''

# Flow Generation Center v2: sleek Bridge/Port status capsule + inline interval controls. UI only.
LIGHT += r'''
QFrame#flowBridgeCapsule {
    background:#FFFFFF; border:1px solid #DCE5F2; border-radius:12px;
}
QLabel#flowBridgeStatus {
    background:#F1F5F9; color:#52627A; border:1px solid #DCE4EF;
    border-radius:9px; padding:4px 11px; font-size:12.5px; font-weight:750;
}
QLabel#flowBridgeStatus[state="online"] {
    background:#E6F7EE; color:#157F4B; border:1px solid #B7E4C9;
}
QLabel#flowPortBadge {
    background:#EEF3FA; color:#33415A; border:1px solid #D8E2F0;
    border-radius:9px; padding:4px 10px; font-size:12px; font-weight:750;
}
QFrame#flowHeaderSep {
    background:#DCE4EF; min-width:1px; max-width:1px; min-height:16px; max-height:16px; border:none;
}
QFrame#flowFirstThreeBox {
    background:#FFFFFF; border:1px solid #DCE5F2; border-radius:10px; min-height:36px;
}
QFrame#flowFirstThreeBox:hover {
    border-color:#93C5FD; background:#F8FBFF;
}
QFrame#flowFirstThreeBox[active="true"] {
    background:#EFF6FF; border:1.5px solid #3B82F6;
}
QCheckBox#flowFirstThreeCheck, QLabel#flowFirstThreeTail {
    color:#334155; font-size:13px; font-weight:750; spacing:7px; background:transparent;
}
QFrame#flowFirstThreeBox[active="true"] QCheckBox#flowFirstThreeCheck,
QFrame#flowFirstThreeBox[active="true"] QLabel#flowFirstThreeTail {
    color:#1D4ED8; font-weight:800;
}
QFrame#flowFirstThreeBox[active="true"] QSpinBox#flowInlineSpin {
    background:#FFFFFF; border:1px solid #93C5FD; color:#1E40AF;
}
QFrame#flowIntervalGroup {
    background:#FFFFFF; border:1px solid #DCE5F2; border-radius:10px;
}
QLabel#flowIntervalLabel {
    color:#475569; font-size:13px; font-weight:750;
}
QSpinBox#flowInlineSpin {
    min-height:28px; max-height:30px; padding:2px 6px 2px 8px;
    border-radius:7px; font-size:13px; font-weight:750;
    background:#F8FAFD; border:1px solid #CFD9E8; color:#182235;
}
QSpinBox#flowInlineSpin:focus {
    background:#FFFFFF; border:1px solid #2F6FED;
}
'''

DARK += r'''
QFrame#flowBridgeCapsule {
    background:#1D242E; border:1px solid #34404E; border-radius:12px;
}
QLabel#flowBridgeStatus {
    background:#252E3A; color:#9AA7BA; border:1px solid #384556;
    border-radius:9px; padding:4px 11px; font-size:12.5px; font-weight:750;
}
QLabel#flowBridgeStatus[state="online"] {
    background:#1B382B; color:#6EE7B7; border:1px solid #2D5E46;
}
QLabel#flowPortBadge {
    background:#242E3D; color:#B8C7DC; border:1px solid #384659;
    border-radius:9px; padding:4px 10px; font-size:12px; font-weight:750;
}
QFrame#flowHeaderSep {
    background:#34404E; min-width:1px; max-width:1px; min-height:16px; max-height:16px; border:none;
}
QFrame#flowFirstThreeBox {
    background:#202834; border:1px solid #354252; border-radius:10px; min-height:36px;
}
QFrame#flowFirstThreeBox:hover {
    border-color:#4B82F1; background:#243041;
}
QFrame#flowFirstThreeBox[active="true"] {
    background:#1E3250; border:1.5px solid #4B82F1;
}
QCheckBox#flowFirstThreeCheck, QLabel#flowFirstThreeTail {
    color:#CBD5E1; font-size:13px; font-weight:750; spacing:7px; background:transparent;
}
QFrame#flowFirstThreeBox[active="true"] QCheckBox#flowFirstThreeCheck,
QFrame#flowFirstThreeBox[active="true"] QLabel#flowFirstThreeTail {
    color:#93C5FD; font-weight:800;
}
QFrame#flowFirstThreeBox[active="true"] QSpinBox#flowInlineSpin {
    background:#16243B; border:1px solid #4B82F1; color:#DBEAFE;
}
QFrame#flowIntervalGroup {
    background:#202834; border:1px solid #354252; border-radius:10px;
}
QLabel#flowIntervalLabel {
    color:#CBD5E1; font-size:13px; font-weight:750;
}
QSpinBox#flowInlineSpin {
    min-height:28px; max-height:30px; padding:2px 6px 2px 8px;
    border-radius:7px; font-size:13px; font-weight:750;
    background:#18202B; border:1px solid #3B4656; color:#EEF3FC;
}
QSpinBox#flowInlineSpin:focus {
    background:#222C3A; border:1px solid #4B82F1;
}
'''

# GPT Prompt Center: centered live processing progress & completion feedback bar.
LIGHT += r'''
QWidget#pcCenterStatusWrap, QWidget#pcCenterProgressBox { background:transparent; }
QFrame#pcCenterStatusCard {
    background:#EFF6FF; border:1.5px solid #93C5FD; border-radius:10px;
}
QFrame#pcCenterStatusCard[tone="running"] {
    background:#EFF6FF; border:1.5px solid #60A5FA;
}
QFrame#pcCenterStatusCard[tone="done"] {
    background:#ECFDF5; border:1.5px solid #6EE7B7;
}
QFrame#pcCenterStatusCard[tone="done"][flash="true"] {
    background:#D1FAE5; border:2px solid #10B981;
}
QFrame#pcCenterStatusCard[tone="warn"] {
    background:#FFFBEB; border:1.5px solid #FBBF24;
}
QFrame#pcCenterStatusCard[tone="warn"][flash="true"] {
    background:#FEF3C7; border:2px solid #D97706;
}
QFrame#pcCenterStatusCard[tone="info"] {
    background:#F5F3FF; border:1.5px solid #C4B5FD;
}
QFrame#pcCenterStatusCard[tone="info"][flash="true"] {
    background:#EDE9FE; border:2px solid #7C3AED;
}

QLabel#pcCenterStateBadge {
    background:#2563EB; color:#FFFFFF; border:none; border-radius:7px;
    padding:3px 9px; font-size:12px; font-weight:800;
}
QLabel#pcCenterStateBadge[tone="running"] { background:#2563EB; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="done"] { background:#10B981; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="warn"] { background:#D97706; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="info"] { background:#6366F1; color:#FFFFFF; }

QLabel#pcCenterJobText {
    background:transparent; color:#1E3A8A; font-size:13px; font-weight:750;
}
QLabel#pcCenterJobText[tone="running"] { color:#1E3A8A; }
QLabel#pcCenterJobText[tone="done"] { color:#065F46; }
QLabel#pcCenterJobText[tone="warn"] { color:#92400E; }
QLabel#pcCenterJobText[tone="info"] { color:#3730A3; }

QProgressBar#pcCenterProgress {
    background:#DBEAFE; border:1px solid #BFDBFE; border-radius:4px;
    min-height:8px; max-height:8px; padding:0px;
}
QProgressBar#pcCenterProgress::chunk {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #3B82F6);
    border-radius:4px;
}
QProgressBar#pcCenterProgress[tone="done"] {
    background:#D1FAE5; border:1px solid #A7F3D0;
}
QProgressBar#pcCenterProgress[tone="done"]::chunk {
    background:#10B981;
}
QProgressBar#pcCenterProgress[tone="warn"] {
    background:#FDE68A; border:1px solid #FCD34D;
}
QProgressBar#pcCenterProgress[tone="warn"]::chunk {
    background:#D97706;
}

QLabel#pcCenterProgressPct {
    background:transparent; color:#1D4ED8; font-size:12.5px; font-weight:800;
}
QLabel#pcCenterProgressPct[tone="done"] { color:#047857; }
QLabel#pcCenterProgressPct[tone="warn"] { color:#B45309; }

QLabel#pcCenterTimeLabel {
    background:transparent; color:#64748B; font-size:11.5px; font-weight:650; padding:0px 2px;
}
QLabel#pcCostChip {
    padding:5px 12px; border-radius:12px;
    background:#ECFDF5; border:1px solid #A7F3D0; color:#065F46;
    font-size:13px; font-weight:800;
}
QPushButton#pcCenterDismissBtn {
    background:transparent; color:#64748B; border:none; border-radius:6px;
    font-size:12px; font-weight:800; padding:0px;
}
QPushButton#pcCenterDismissBtn:hover {
    background:rgba(15, 23, 42, 0.08); color:#0F172A;
}
'''

DARK += r'''
QWidget#pcCenterStatusWrap, QWidget#pcCenterProgressBox { background:transparent; }
QFrame#pcCenterStatusCard {
    background:#172554; border:1.5px solid #3B82F6; border-radius:10px;
}
QFrame#pcCenterStatusCard[tone="running"] {
    background:#172554; border:1.5px solid #3B82F6;
}
QFrame#pcCenterStatusCard[tone="done"] {
    background:#064E3B; border:1.5px solid #10B981;
}
QFrame#pcCenterStatusCard[tone="done"][flash="true"] {
    background:#065F46; border:2px solid #34D399;
}
QFrame#pcCenterStatusCard[tone="warn"] {
    background:#451A03; border:1.5px solid #F59E0B;
}
QFrame#pcCenterStatusCard[tone="warn"][flash="true"] {
    background:#78350F; border:2px solid #FBBF24;
}
QFrame#pcCenterStatusCard[tone="info"] {
    background:#1E1B4B; border:1.5px solid #818CF8;
}
QFrame#pcCenterStatusCard[tone="info"][flash="true"] {
    background:#312E81; border:2px solid #A5B4FC;
}

QLabel#pcCenterStateBadge {
    background:#2563EB; color:#FFFFFF; border:none; border-radius:7px;
    padding:3px 9px; font-size:12px; font-weight:800;
}
QLabel#pcCenterStateBadge[tone="running"] { background:#2563EB; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="done"] { background:#059669; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="warn"] { background:#D97706; color:#FFFFFF; }
QLabel#pcCenterStateBadge[tone="info"] { background:#4F46E5; color:#FFFFFF; }

QLabel#pcCenterJobText {
    background:transparent; color:#DBEAFE; font-size:13px; font-weight:750;
}
QLabel#pcCenterJobText[tone="running"] { color:#DBEAFE; }
QLabel#pcCenterJobText[tone="done"] { color:#D1FAE5; }
QLabel#pcCenterJobText[tone="warn"] { color:#FEF3C7; }
QLabel#pcCenterJobText[tone="info"] { color:#E0E7FF; }

QProgressBar#pcCenterProgress {
    background:#1E3A8A; border:1px solid #2563EB; border-radius:4px;
    min-height:8px; max-height:8px; padding:0px;
}
QProgressBar#pcCenterProgress::chunk {
    background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #60A5FA);
    border-radius:4px;
}
QProgressBar#pcCenterProgress[tone="done"] {
    background:#065F46; border:1px solid #059669;
}
QProgressBar#pcCenterProgress[tone="done"]::chunk {
    background:#34D399;
}
QProgressBar#pcCenterProgress[tone="warn"] {
    background:#78350F; border:1px solid #D97706;
}
QProgressBar#pcCenterProgress[tone="warn"]::chunk {
    background:#FBBF24;
}

QLabel#pcCenterProgressPct {
    background:transparent; color:#93C5FD; font-size:12.5px; font-weight:800;
}
QLabel#pcCenterProgressPct[tone="done"] { color:#6EE7B7; }
QLabel#pcCenterProgressPct[tone="warn"] { color:#FCD34D; }

QLabel#pcCenterTimeLabel {
    background:transparent; color:#94A3B8; font-size:11.5px; font-weight:650; padding:0px 2px;
}
QLabel#pcCostChip {
    padding:5px 12px; border-radius:12px;
    background:#064E3B; border:1px solid #059669; color:#A7F3D0;
    font-size:13px; font-weight:800;
}
QPushButton#pcCenterDismissBtn {
    background:transparent; color:#94A3B8; border:none; border-radius:6px;
    font-size:12px; font-weight:800; padding:0px;
}
QPushButton#pcCenterDismissBtn:hover {
    background:rgba(255, 255, 255, 0.12); color:#F8FAFC;
}
'''

# GPT Prompt Center: adaptive Quick Editor (2 compact top rule boxes + side-by-side large studio image & expanding prompt).
LIGHT += r'''
QFrame#pcEditorThumb, QLabel#pcEditorThumb {
    background:#F4F7FC; border:1px solid #D5DFEC; border-radius:9px;
    color:#7A889B; font-size:12.5px; font-weight:700;
}
QFrame#pcEditorThumb[hasImage="true"]:hover, QLabel#pcEditorThumb[hasImage="true"]:hover {
    border:1.5px solid #3B82F6; background:#ECF3FF;
}
QPlainTextEdit#pcCompactRuleEdit {
    background:#FAFBFD; color:#182235; border:1px solid #D7E0EC;
    border-radius:8px; padding:4px 7px; font-size:12.5px;
}
QPlainTextEdit#pcCompactRuleEdit:focus {
    background:#FFFFFF; border:1.5px solid #3B82F6;
}
QPlainTextEdit#pcFinalPromptEdit {
    background:#FFFFFF; color:#182235; border:1px solid #D5DFEC;
    border-radius:9px; padding:6px 9px; font-size:13px;
}
QPlainTextEdit#pcFinalPromptEdit:focus {
    border:1.5px solid #3B82F6;
}
QLabel#pcEditorFieldLabel {
    color:#2B3A55; font-size:12px; font-weight:750;
}
QPushButton#pcMiniCopyBtn {
    background:#F1F5F9; color:#475569; border:1px solid #DCE4EF;
    border-radius:6px; padding:2px 8px; font-size:11.5px; font-weight:700;
    min-height:22px; max-height:22px;
}
QPushButton#pcMiniCopyBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE;
}
QDialog#pcImageZoomDialog {
    background:#FFFFFF; color:#182235;
}
'''

DARK += r'''
QFrame#pcEditorThumb, QLabel#pcEditorThumb {
    background:#1F2733; border:1px solid #3A4759; border-radius:9px;
    color:#8E9DB2; font-size:12.5px; font-weight:700;
}
QFrame#pcEditorThumb[hasImage="true"]:hover, QLabel#pcEditorThumb[hasImage="true"]:hover {
    border:1.5px solid #60A5FA; background:#253142;
}
QPlainTextEdit#pcCompactRuleEdit {
    background:#1F2733; color:#EDF2F8; border:1px solid #384556;
    border-radius:8px; padding:4px 7px; font-size:12.5px;
}
QPlainTextEdit#pcCompactRuleEdit:focus {
    background:#232D3B; border:1.5px solid #4B82F1;
}
QPlainTextEdit#pcFinalPromptEdit {
    background:#202834; color:#F2F5F9; border:1px solid #3A4759;
    border-radius:9px; padding:6px 9px; font-size:13px;
}
QPlainTextEdit#pcFinalPromptEdit:focus {
    border:1.5px solid #4B82F1;
}
QLabel#pcEditorFieldLabel {
    color:#CBD5E1; font-size:12px; font-weight:750;
}
QPushButton#pcMiniCopyBtn {
    background:#252E3A; color:#CBD5E1; border:1px solid #384556;
    border-radius:6px; padding:2px 8px; font-size:11.5px; font-weight:700;
    min-height:22px; max-height:22px;
}
QPushButton#pcMiniCopyBtn:hover {
    background:#1E3A5F; color:#93C5FD; border-color:#3B82F6;
}
QDialog#pcImageZoomDialog {
    background:#161C24; color:#E8EDF5;
}
'''

# Theme consistency & high-contrast Dark Mode polish across Prompt Center, Video QC Center, Auto-Edit & Dialogs. UI only.
LIGHT += r'''
QScrollArea#filterScrollArea { background:transparent; border:none; }
QScrollArea#filterScrollArea QScrollBar:horizontal { height:4px; background:transparent; margin:0px 2px 1px 2px; }
QScrollArea#filterScrollArea QScrollBar::handle:horizontal { background:#CBD5E1; border-radius:2px; min-width:24px; }
QScrollArea#filterScrollArea QScrollBar::add-line:horizontal,
QScrollArea#filterScrollArea QScrollBar::sub-line:horizontal { width:0px; height:0px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height:0px; width:0px; border:none; background:none;
}
QAbstractScrollArea::corner { background:transparent; border:none; }

QSplitter#pcWorkspaceSplitter::handle { background:#E2E8F0; border-radius:3px; margin:2px; }
QSplitter#pcWorkspaceSplitter::handle:hover { background:#93C5FD; }

QTableWidget#promptTaskTable {
    background:#FFFFFF;
    alternate-background-color:#FFFFFF;
    color:#182235;
    border:1px solid #DCE4EF;
    border-radius:9px;
    gridline-color:#E5ECF5;
    selection-background-color:#EFF6FF;
    selection-color:#182235;
}
QTableWidget#promptTaskTable QHeaderView::section {
    background:#F3F6FB; color:#334155;
    border:none; border-right:1px solid #E2E8F0; border-bottom:1px solid #DCE4EF;
    padding:7px 8px; font-size:12.5px; font-weight:750;
}

QLabel#miniTagSubmitted {
    background:#DCFCE7; color:#15803D; border:1px solid #86EFAC;
    border-radius:4px; padding:1px 6px; font-size:11px; font-weight:700;
}
QLabel#pcDurationLabel { font-size:12px; font-weight:600; color:#475569; }
QLabel#pcDurationLabel[tone="good"] { color:#15803D; font-weight:600; }
QLabel#pcDurationLabel[tone="warn"] { color:#D97706; font-weight:700; }
QLabel#pcDurationLabel[tone="danger"] { color:#DC2626; font-weight:700; }
QLabel#pcDurationLabel[tone="muted"] { color:#475569; font-weight:600; }

QDialog#pcWithdrawDialog { background:#F8FAFC; color:#0F172A; }
QLabel#pcWithdrawTitle { font-size:16px; font-weight:800; color:#DC2626; }
QLabel#pcWithdrawDesc {
    font-size:13px; color:#1E293B;
    background:#FFF1F2; border:1px solid #FECDD3; border-radius:10px; padding:12px 14px;
}
QPushButton#pcWithdrawAbortBtn {
    background:#FFF1F2; color:#E11D48; border:1.5px solid #FDA4AF;
    border-radius:9px; padding:0 16px; font-size:13.5px; font-weight:800;
}
QPushButton#pcWithdrawAbortBtn:hover { background:#FFE4E6; border-color:#F43F5E; }

/* Video QC Center (视频质检中心) */
QLabel#qcPageTitle { font-size:22px; font-weight:800; color:#0F172A; }
QLabel#qcPageSub { font-size:12.5px; color:#64748B; }
QFrame#qcMetricPill { background:#F8FAFC; border:1px solid #E2E8F0; border-radius:9px; }
QFrame#qcMetricPill[tone="info"] { background:#EFF6FF; border:1px solid #BFDBFE; }
QFrame#qcMetricPill[tone="good"] { background:#F0FDF4; border:1px solid #BBF7D0; }
QFrame#qcMetricPill[tone="bad"] { background:#FEF2F2; border:1px solid #FECACA; }
QFrame#qcMetricPill[tone="neutral"] { background:#F8FAFC; border:1px solid #E2E8F0; }
QLabel#qcMetricTitle { font-size:12px; font-weight:650; color:#475569; background:transparent; border:none; padding:0 2px; }
QLabel#qcMetricTitle[tone="info"] { color:#1D4ED8; }
QLabel#qcMetricTitle[tone="good"] { color:#15803D; }
QLabel#qcMetricTitle[tone="bad"] { color:#DC2626; }
QLabel#qcMetricTitle[tone="neutral"] { color:#475569; }
QLabel#metricValue[qcMetric="true"] { font-size:14px; font-weight:800; color:#475569; background:transparent; border:none; }
QLabel#metricValue[qcMetric="true"][tone="info"] { color:#1D4ED8; }
QLabel#metricValue[qcMetric="true"][tone="good"] { color:#15803D; }
QLabel#metricValue[qcMetric="true"][tone="bad"] { color:#DC2626; }
QLabel#metricValue[qcMetric="true"][tone="neutral"] { color:#475569; }

QLabel#qcSectionTitle { font-size:15px; font-weight:800; color:#0F172A; }
QLabel#qcSubSectionTitle { font-size:12.5px; font-weight:750; color:#334155; }
QLabel#qcCountChip { font-size:12px; font-weight:700; color:#475569; background:#F1F5F9; border:1px solid #E2E8F0; border-radius:6px; padding:2px 8px; }
QLabel#qcCurrentBadge { font-size:14px; font-weight:800; color:#1D4ED8; background:#EFF6FF; border:1px solid #BFDBFE; border-radius:7px; padding:3px 10px; }
QLabel#qcHintText { font-size:11.5px; color:#475569; }
QLabel#qcTimeLabel { color:#334155; font-size:12.5px; font-weight:700; min-width:42px; }
QCheckBox#qcPlayerCheck { color:#334155; font-size:12.5px; font-weight:650; min-height:34px; }
QFrame#qcPlayerFooter {
    background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px;
}
QSlider#qcSeekSlider { min-height:22px; background:transparent; }
QSlider#qcSeekSlider::groove:horizontal { height:6px; background:#CBD5E1; border-radius:3px; }
QSlider#qcSeekSlider::sub-page:horizontal { background:#2F6FED; border-radius:3px; }
QSlider#qcSeekSlider::handle:horizontal {
    background:#2F6FED; border:2px solid #FFFFFF; width:14px; height:14px;
    margin:-5px 0; border-radius:8px;
}

QPushButton#qcViewToggleBtn {
    min-height:0px; max-height:30px; padding:4px 10px; font-size:12px; font-weight:650;
    background:#F8FAFC; color:#475569; border:1px solid #D8E1EE; border-radius:7px;
}
QPushButton#qcViewToggleBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD; }
QPushButton#qcViewToggleBtn:checked {
    background:#2F6FED; color:#FFFFFF; border:1px solid #2F6FED; font-weight:750;
}
QPushButton#qcRefreshBtn {
    min-height:0px; max-height:32px; padding:0 12px; font-size:12px; font-weight:650;
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1; border-radius:7px;
}
QPushButton#qcRefreshBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD; }

QPushButton#qcMiniActionBtn {
    min-height:0px; max-height:28px; padding:3px 9px; font-size:12px; font-weight:650;
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1; border-radius:7px;
}
QPushButton#qcMiniActionBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD; }
QPushButton#qcMiniActionBtn:disabled { background:#F1F5F9; color:#94A3B8; border-color:#E2E8F0; }

QFrame#qcInfoCard, QFrame#qcScriptCard {
    background:#F8FAFC; border:1px solid #E2E8F0; border-radius:9px;
}
QLabel#qcInfoLabel { font-size:12px; color:#64748B; font-weight:600; background:transparent; border:none; }
QLabel#qcInfoValue { font-size:13px; font-weight:750; color:#0F172A; background:transparent; border:none; }
QLabel#qcInfoHost { font-size:13.5px; font-weight:800; color:#1D4ED8; background:transparent; border:none; }
QLabel#qcStatusBadge { font-size:12.5px; font-weight:700; color:#64748B; background:transparent; border:none; }
QLabel#qcStatusBadge[state="passed"] { font-weight:800; color:#15803D; background:#DCFCE7; border-radius:6px; padding:1px 8px; }
QLabel#qcStatusBadge[state="rework"] { font-weight:800; color:#DC2626; background:#FEE2E2; border-radius:6px; padding:1px 8px; }
QLabel#qcStatusBadge[state="pending"] { font-weight:800; color:#1D4ED8; background:#DBEAFE; border-radius:6px; padding:1px 8px; }

QLabel#qcScriptTag { font-size:11.5px; font-weight:700; color:#475569; background:transparent; border:none; }
QLabel#qcModeLabel { font-size:11.5px; color:#64748B; background:transparent; border:none; }
QLineEdit#qcForeignCopy {
    background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px;
    padding:5px 8px; font-size:13px; color:#0F172A; font-weight:500;
}

QSplitter#qcMainSplitter::handle { background:#DCE6F2; border-radius:4px; margin:2px; }
QSplitter#qcMainSplitter::handle:hover { background:#AFC3DF; }
QScrollArea#segmentScroll { border:none; background:transparent; }
QScrollArea#segmentScroll QWidget#qt_scrollarea_viewport,
QWidget#segmentScrollContent { background:transparent; }

QLabel#qcPreviewTitle {
    font-size:14px; font-weight:750; color:#1E293B;
    background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:6px 12px;
}
QPushButton#qcPlayerChipBtn {
    min-height:34px; max-height:34px; padding:0px 13px; font-size:13px; font-weight:700;
    background:#FFFFFF; color:#1E293B; border:1px solid #CBD5E1; border-radius:8px;
}
QPushButton#qcPlayerChipBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD; }
QPushButton#qcPlayerChipBtn[adjusted="true"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #93C5FD; font-weight:750;
}
QPushButton#qcPlayerChipBtn[adjusted="true"]:hover { background:#DBEAFE; border-color:#60A5FA; }
QPushButton#qcPlayerChipBtn[boosted="true"] {
    background:#2F6FED; color:#FFFFFF; border:1px solid #2F6FED; font-weight:750;
}
QPushButton#qcPlayerChipBtn[boosted="true"]:hover { background:#255BD0; border-color:#255BD0; }

QPushButton#qcPlayerIconBtn {
    min-width:42px; max-width:42px; min-height:34px; max-height:34px;
    padding:0px; border:1px solid #CBD5E1; border-radius:8px;
    background:#FFFFFF; font-size:17px; color:#1E293B; font-weight:bold;
}
QPushButton#qcPlayerIconBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }

QFrame#taskRow { border:1px solid #E2E8F0; background:#FFFFFF; border-radius:9px; min-height:48px; }
QFrame#taskRow:hover { border-color:#93C5FD; background:#F8FAFC; }
QFrame#taskRow[active="true"] { border:1.5px solid #2F6FED; background:#EFF6FF; border-radius:9px; min-height:48px; }
QFrame#taskRow QPushButton#hostSelect {
    background:transparent; border:none; text-align:left; padding:4px 6px;
    font-size:13px; font-weight:700; color:#0F172A;
}
QFrame#taskRow QPushButton#hostSelectActive {
    background:transparent; border:none; text-align:left; padding:4px 6px;
    font-size:13.5px; font-weight:800; color:#1D4ED8;
}
QLabel#qcHostCount {
    font-size:12px; font-weight:750; color:#475569; background:#F1F5F9;
    border-radius:6px; padding:2px 8px;
}
QFrame#taskGroup QLabel#cardTitle[qcRecipient="true"] {
    font-size:12.5px; font-weight:800; color:#475569; padding-left:2px;
}
QFrame#taskGroup QLabel#cardTitle[qcBottomTitle="true"] {
    font-size:13px; font-weight:800; color:#0F172A;
}
QLabel#qcLegendChip {
    font-size:11.5px; color:#64748B; background:#F1F5F9; border-radius:5px; padding:2px 7px;
}
QLabel#qcEmptyLabel {
    color:#64748B; font-size:13px; font-weight:600; padding:28px 12px;
    background:#F8FAFC; border:1px dashed #CBD5E1; border-radius:10px;
}
QPushButton#qcVideoSeqBtn {
    background:#F4F7FB; color:#33415A; border:1px solid #DDE5F0;
    border-radius:8px; font-size:13px; font-weight:800; padding:0px;
    min-width:42px; max-width:42px; min-height:38px; max-height:38px;
}
QPushButton#qcVideoSeqBtn:disabled { background:#F4F7FB; color:#64748B; border:1px solid #DDE5F0; }
QPushButton#qcVideoSeqBtn[qcState="passed"],
QPushButton#qcVideoSeqBtn[qcState="passed"]:disabled {
    background:#E9F8F0; color:#178656; border:1px solid #B8E3CA;
}
QPushButton#qcVideoSeqBtn[qcCurrent="true"],
QPushButton#qcVideoSeqBtn[qcCurrent="true"]:disabled {
    border:2px solid #2F6FED;
}
QPushButton#qcVideoSeqBtn:hover { border-color:#6E9AF5; }

QLabel#clipTransformNote { color:#334155; font-size:12.5px; }
QLabel#clipTransformFieldLbl { font-weight:700; color:#1E293B; }
QLabel#clipTransformPresetLbl { color:#64748B; font-size:12px; }
QPushButton#clipTransformResetBtn {
    min-height:0px; background:#F8FAFC; color:#475569; border:1px solid #CBD5E1;
    border-radius:6px; padding:0px; font-size:11.5px; font-weight:600;
}
QPushButton#clipTransformResetBtn:hover { background:#E2E8F0; color:#0F172A; }
QPushButton#clipTransformPresetBtn {
    min-height:0px; background:#F1F5F9; color:#1E293B; border:1px solid #CBD5E1;
    border-radius:6px; padding:0 8px; font-size:11.5px; font-weight:600;
}
QPushButton#clipTransformPresetBtn:hover { background:#E2E8F0; border-color:#94A3B8; }
QFrame#customModeBox { background:#F8FAFC; border:1px solid #CBD5E1; border-radius:6px; padding:6px; }
'''

DARK += r'''
QScrollArea#filterScrollArea { background:transparent; border:none; }
QScrollArea#filterScrollArea QScrollBar:horizontal { height:4px; background:transparent; margin:0px 2px 1px 2px; }
QScrollArea#filterScrollArea QScrollBar::handle:horizontal { background:#475569; border-radius:2px; min-width:24px; }
QScrollArea#filterScrollArea QScrollBar::add-line:horizontal,
QScrollArea#filterScrollArea QScrollBar::sub-line:horizontal { width:0px; height:0px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height:0px; width:0px; border:none; background:none;
}
QAbstractScrollArea::corner { background:transparent; border:none; }

QSplitter#pcWorkspaceSplitter::handle { background:#2A3444; border-radius:3px; margin:2px; }
QSplitter#pcWorkspaceSplitter::handle:hover { background:#4B82F1; }

QPushButton#pcBtn[tier="l2blue"] { background:#1B2B44; color:#93C5FD; border:1.5px solid #3B82F6; }
QPushButton#pcBtn[tier="l2blue"]:hover { background:#22385A; border-color:#60A5FA; }
QPushButton#pcBtn[tier="l2green"] { background:#163026; color:#86EFAC; border:1.5px solid #22C55E; }
QPushButton#pcBtn[tier="l2green"]:hover { background:#1C3D30; border-color:#4ADE80; }
QPushButton#pcBtn[tier="l2"] { background:#222C3A; color:#F1F5F9; border:1.5px solid #52657E; }
QPushButton#pcBtn[tier="l2"]:hover { background:#2B384A; border-color:#758CA8; }
QPushButton#pcBtn[tier="l3"] { background:#263040; color:#E2E8F0; border:1px solid #384659; font-weight:650; }
QPushButton#pcBtn[tier="l3"]:hover { background:#303D50; border-color:#4B5E78; color:#FFFFFF; }
QPushButton#pcBtn:disabled { background:#1A212B; color:#64748B; border:1px solid #283240; }

QPushButton#eyeTypeOpen, QPushButton#eyeTypeClosed {
    background:#19202B; color:#8B9AB0; border:1px solid #334052;
}
QPushButton#eyeTypeOpen:hover, QPushButton#eyeTypeClosed:hover { background:#232D3B; color:#CBD5E1; }
QPushButton#eyeTypeOpen:checked { background:#1E3A64; color:#BFDBFE; border-color:#4B82F1; }
QPushButton#eyeTypeClosed:checked { background:#34264C; color:#DDD6FE; border-color:#8B5CF6; }

QPushButton#generationModeFrame, QPushButton#generationModeMaterial {
    background:#19202B; color:#8B9AB0; border:1px solid #334052;
}
QPushButton#generationModeFrame:hover, QPushButton#generationModeMaterial:hover { background:#232D3B; color:#CBD5E1; }
QPushButton#generationModeFrame:checked { background:#1E3A64; color:#BFDBFE; border-color:#4B82F1; }
QPushButton#generationModeMaterial:checked { background:#163829; color:#6EE7B7; border-color:#22C55E; }

QTableWidget#promptTaskTable {
    background:#1D242E;
    alternate-background-color:#1D242E;
    color:#EDF2F8;
    border:1px solid #323E4E;
    border-radius:9px;
    gridline-color:#2B3646;
    selection-background-color:#223148;
    selection-color:#F8FAFC;
}
QTableWidget#promptTaskTable QHeaderView::section {
    background:#242E3D; color:#CBD5E1;
    border:none; border-right:1px solid #323E4E; border-bottom:1px solid #364355;
    padding:7px 8px; font-size:12.5px; font-weight:750;
}

QLabel#miniTagSubmitted {
    background:#163829; color:#6EE7B7; border:1px solid #286448;
    border-radius:4px; padding:1px 6px; font-size:11px; font-weight:700;
}
QLabel#pcDurationLabel { font-size:12px; font-weight:600; color:#CBD5E1; }
QLabel#pcDurationLabel[tone="good"] { color:#4ADE80; font-weight:600; }
QLabel#pcDurationLabel[tone="warn"] { color:#FBBF24; font-weight:700; }
QLabel#pcDurationLabel[tone="danger"] { color:#F87171; font-weight:700; }
QLabel#pcDurationLabel[tone="muted"] { color:#CBD5E1; font-weight:600; }

QDialog#pcWithdrawDialog { background:#151A22; color:#F1F5F9; }
QLabel#pcWithdrawTitle { font-size:16px; font-weight:800; color:#F87171; }
QLabel#pcWithdrawDesc {
    font-size:13px; color:#E2E8F0;
    background:#2A1A20; border:1px solid #6E323B; border-radius:10px; padding:12px 14px;
}
QPushButton#pcWithdrawAbortBtn {
    background:#2A1A20; color:#FDA4AF; border:1.5px solid #881337;
    border-radius:9px; padding:0 16px; font-size:13.5px; font-weight:800;
}
QPushButton#pcWithdrawAbortBtn:hover { background:#3B1F27; border-color:#E11D48; }

/* Video QC Center (视频质检中心) */
QLabel#qcPageTitle { font-size:22px; font-weight:800; color:#F1F5F9; }
QLabel#qcPageSub { font-size:12.5px; color:#94A3B8; }
QFrame#qcMetricPill { background:#222B38; border:1px solid #364355; border-radius:9px; }
QFrame#qcMetricPill[tone="info"] { background:#1B2E4B; border:1px solid #2F548A; }
QFrame#qcMetricPill[tone="good"] { background:#163528; border:1px solid #265C43; }
QFrame#qcMetricPill[tone="bad"] { background:#3B1F24; border:1px solid #6E323B; }
QFrame#qcMetricPill[tone="neutral"] { background:#222B38; border:1px solid #364355; }
QLabel#qcMetricTitle { font-size:12px; font-weight:650; color:#CBD5E1; background:transparent; border:none; padding:0 2px; }
QLabel#qcMetricTitle[tone="info"] { color:#93C5FD; }
QLabel#qcMetricTitle[tone="good"] { color:#6EE7B7; }
QLabel#qcMetricTitle[tone="bad"] { color:#FCA5A5; }
QLabel#qcMetricTitle[tone="neutral"] { color:#CBD5E1; }
QLabel#metricValue[qcMetric="true"] { font-size:14px; font-weight:800; color:#F1F5F9; background:transparent; border:none; }
QLabel#metricValue[qcMetric="true"][tone="info"] { color:#BFDBFE; }
QLabel#metricValue[qcMetric="true"][tone="good"] { color:#A7F3D0; }
QLabel#metricValue[qcMetric="true"][tone="bad"] { color:#FECACA; }
QLabel#metricValue[qcMetric="true"][tone="neutral"] { color:#F1F5F9; }

QLabel#qcSectionTitle { font-size:15px; font-weight:800; color:#F1F5F9; }
QLabel#qcSubSectionTitle { font-size:12.5px; font-weight:750; color:#CBD5E1; }
QLabel#qcCountChip { font-size:12px; font-weight:700; color:#CBD5E1; background:#252F3E; border:1px solid #364355; border-radius:6px; padding:2px 8px; }
QLabel#qcCurrentBadge { font-size:14px; font-weight:800; color:#93C5FD; background:#1E3A5F; border:1px solid #3B82F6; border-radius:7px; padding:3px 10px; }
QLabel#qcHintText { font-size:11.5px; color:#A8B6C8; }
QLabel#qcTimeLabel { color:#E2E8F0; font-size:12.5px; font-weight:700; min-width:42px; }
QCheckBox#qcPlayerCheck { color:#CBD5E1; font-size:12.5px; font-weight:650; min-height:34px; }
QFrame#qcPlayerFooter {
    background:#161E29; border:1px solid #2E3A4B; border-radius:10px;
}
QSlider#qcSeekSlider { min-height:22px; background:transparent; }
QSlider#qcSeekSlider::groove:horizontal { height:6px; background:#334155; border-radius:3px; }
QSlider#qcSeekSlider::sub-page:horizontal { background:#3B82F6; border-radius:3px; }
QSlider#qcSeekSlider::handle:horizontal {
    background:#60A5FA; border:2px solid #0F172A; width:14px; height:14px;
    margin:-5px 0; border-radius:8px;
}

QPushButton#qcViewToggleBtn {
    min-height:0px; max-height:30px; padding:4px 10px; font-size:12px; font-weight:650;
    background:#252F3E; color:#CBD5E1; border:1px solid #3A485C; border-radius:7px;
}
QPushButton#qcViewToggleBtn:hover { background:#2E3B4E; color:#FFFFFF; border-color:#4B6EA8; }
QPushButton#qcViewToggleBtn:checked {
    background:#2563EB; color:#FFFFFF; border:1px solid #3B82F6; font-weight:750;
}
QPushButton#qcRefreshBtn {
    min-height:0px; max-height:32px; padding:0 12px; font-size:12px; font-weight:650;
    background:#252F3E; color:#E2E8F0; border:1px solid #3A485C; border-radius:7px;
}
QPushButton#qcRefreshBtn:hover { background:#1E3A5F; color:#93C5FD; border-color:#3B82F6; }

QPushButton#qcMiniActionBtn {
    min-height:0px; max-height:28px; padding:3px 9px; font-size:12px; font-weight:650;
    background:#252F3E; color:#E2E8F0; border:1px solid #3A485C; border-radius:7px;
}
QPushButton#qcMiniActionBtn:hover { background:#1E3A5F; color:#93C5FD; border-color:#3B82F6; }
QPushButton#qcMiniActionBtn:disabled { background:#1A212B; color:#64748B; border-color:#283240; }

QFrame#qcInfoCard, QFrame#qcScriptCard {
    background:#18202A; border:1px solid #2E3A4B; border-radius:9px;
}
QLabel#qcInfoLabel { font-size:12px; color:#8E9DB2; font-weight:600; background:transparent; border:none; }
QLabel#qcInfoValue { font-size:13px; font-weight:750; color:#F1F5F9; background:transparent; border:none; }
QLabel#qcInfoHost { font-size:13.5px; font-weight:800; color:#7AB4FF; background:transparent; border:none; }
QLabel#qcStatusBadge { font-size:12.5px; font-weight:700; color:#94A3B8; background:transparent; border:none; }
QLabel#qcStatusBadge[state="passed"] { font-weight:800; color:#6EE7B7; background:#163829; border:1px solid #286448; border-radius:6px; padding:1px 8px; }
QLabel#qcStatusBadge[state="rework"] { font-weight:800; color:#FCA5A5; background:#3B1F24; border:1px solid #6E323B; border-radius:6px; padding:1px 8px; }
QLabel#qcStatusBadge[state="pending"] { font-weight:800; color:#93C5FD; background:#1E3A5F; border:1px solid #335C99; border-radius:6px; padding:1px 8px; }

QLabel#qcScriptTag { font-size:11.5px; font-weight:700; color:#CBD5E1; background:transparent; border:none; }
QLabel#qcModeLabel { font-size:11.5px; color:#8E9DB2; background:transparent; border:none; }
QLineEdit#qcForeignCopy {
    background:#212B38; border:1px solid #354356; border-radius:6px;
    padding:5px 8px; font-size:13px; color:#F1F5F9; font-weight:500;
}

QSplitter#qcMainSplitter::handle { background:#2A3442; border-radius:4px; margin:2px; }
QSplitter#qcMainSplitter::handle:hover { background:#4B82F1; }
QScrollArea#segmentScroll { border:none; background:transparent; }
QScrollArea#segmentScroll QWidget#qt_scrollarea_viewport,
QWidget#segmentScrollContent { background:transparent; }

QLabel#qcPreviewTitle {
    font-size:14px; font-weight:750; color:#F1F5F9;
    background:#18202A; border:1px solid #2E3A4B; border-radius:8px; padding:6px 12px;
}
QPushButton#qcPlayerChipBtn {
    min-height:34px; max-height:34px; padding:0px 13px; font-size:13px; font-weight:700;
    background:#252F3E; color:#F1F5F9; border:1px solid #415168; border-radius:8px;
}
QPushButton#qcPlayerChipBtn:hover { background:#1E3A5F; color:#93C5FD; border-color:#3B82F6; }
QPushButton#qcPlayerChipBtn[adjusted="true"] {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6; font-weight:750;
}
QPushButton#qcPlayerChipBtn[adjusted="true"]:hover { background:#244775; border-color:#60A5FA; }
QPushButton#qcPlayerChipBtn[boosted="true"] {
    background:#2563EB; color:#FFFFFF; border:1px solid #3B82F6; font-weight:750;
}
QPushButton#qcPlayerChipBtn[boosted="true"]:hover { background:#3B82F6; border-color:#60A5FA; }

QPushButton#qcPlayerIconBtn {
    min-width:42px; max-width:42px; min-height:34px; max-height:34px;
    padding:0px; border:1px solid #415168; border-radius:8px;
    background:#252F3E; font-size:17px; color:#F8FAFC; font-weight:bold;
}
QPushButton#qcPlayerIconBtn:hover { background:#1E3A5F; color:#93C5FD; border-color:#3B82F6; }

QFrame#taskRow { border:1px solid #344152; background:#222B37; border-radius:9px; min-height:48px; }
QFrame#taskRow:hover { border-color:#4B6EA8; background:#283342; }
QFrame#taskRow[active="true"] { border:1.5px solid #4B82F1; background:#1D3251; border-radius:9px; min-height:48px; }
QFrame#taskRow QPushButton#hostSelect {
    background:transparent; border:none; text-align:left; padding:4px 6px;
    font-size:13px; font-weight:700; color:#ECF2F9;
}
QFrame#taskRow QPushButton#hostSelectActive {
    background:transparent; border:none; text-align:left; padding:4px 6px;
    font-size:13.5px; font-weight:800; color:#8AB4FF;
}
QLabel#qcHostCount {
    font-size:12px; font-weight:750; color:#CBD5E1; background:#18202A;
    border:1px solid #2F3C4E; border-radius:6px; padding:2px 8px;
}
QFrame#taskGroup QLabel#cardTitle[qcRecipient="true"] {
    font-size:12.5px; font-weight:800; color:#94A3B8; padding-left:2px;
}
QFrame#taskGroup QLabel#cardTitle[qcBottomTitle="true"] {
    font-size:13px; font-weight:800; color:#F1F5F9;
}
QLabel#qcLegendChip {
    font-size:11.5px; color:#94A3B8; background:#252F3E; border:1px solid #354254;
    border-radius:5px; padding:2px 7px;
}
QLabel#qcEmptyLabel {
    color:#94A3B8; font-size:13px; font-weight:600; padding:28px 12px;
    background:#1A222D; border:1px dashed #3A4759; border-radius:10px;
}
QPushButton#qcVideoSeqBtn {
    background:#252E3A; color:#D8E2EF; border:1px solid #3B4656;
    border-radius:8px; font-size:13px; font-weight:800; padding:0px;
    min-width:42px; max-width:42px; min-height:38px; max-height:38px;
}
QPushButton#qcVideoSeqBtn:disabled { background:#202833; color:#7F8CA0; border:1px solid #323D4B; }
QPushButton#qcVideoSeqBtn[qcState="passed"],
QPushButton#qcVideoSeqBtn[qcState="passed"]:disabled {
    background:#183B2F; color:#70E0A6; border:1px solid #2D654E;
}
QPushButton#qcVideoSeqBtn[qcCurrent="true"],
QPushButton#qcVideoSeqBtn[qcCurrent="true"]:disabled {
    border:2px solid #4B82F1; color:#FFFFFF;
}
QPushButton#qcVideoSeqBtn:hover { border-color:#75A2FF; }

QLabel#clipTransformNote { color:#CBD5E1; font-size:12.5px; }
QLabel#clipTransformFieldLbl { font-weight:700; color:#F1F5F9; }
QLabel#clipTransformPresetLbl { color:#94A3B8; font-size:12px; }
QPushButton#clipTransformResetBtn {
    min-height:0px; background:#252F3E; color:#CBD5E1; border:1px solid #3A485C;
    border-radius:6px; padding:0px; font-size:11.5px; font-weight:600;
}
QPushButton#clipTransformResetBtn:hover { background:#1E3A5F; color:#93C5FD; border-color:#3B82F6; }
QPushButton#clipTransformPresetBtn {
    min-height:0px; background:#252F3E; color:#E2E8F0; border:1px solid #3A485C;
    border-radius:6px; padding:0 8px; font-size:11.5px; font-weight:600;
}
QPushButton#clipTransformPresetBtn:hover { background:#303D50; border-color:#5A6E8A; }
QFrame#customModeBox { background:#1D242E; border:1px solid #34404E; border-radius:6px; padding:6px; }
'''

# GPT Prompt Center v5 (Custom Plan A "全直点清爽版"): clickable host cards, flat segmented pills,
# unified font capsule, single-pill eye/mode toggles, and core/full prompt view toggle. UI only.
LIGHT += r'''
QFrame#hostCard {
    background:#FFFFFF; border:1px solid #DCE5F0; border-radius:12px;
}
QFrame#hostCard:hover {
    background:#F8FBFF; border:1.5px solid #93C5FD;
}
QFrame#hostCard[selected="true"] {
    background:#EFF6FF; border:2px solid #2563EB;
}
QFrame#hostCard[selected="true"]:hover {
    background:#EBF4FF; border:2px solid #1D4ED8;
}
QLabel#miniTagSubmitted {
    background:#DCFCE7; color:#15803D; border:1px solid #86EFAC;
    border-radius:8px; padding:1px 6px; font-size:11px; font-weight:800;
}
QPushButton#pcHostPersonaBtn {
    background:#F8FAFC; color:#1E293B; border:1px solid #CBD5E1;
    border-radius:8px; padding:0px 10px; font-size:12.5px; font-weight:750;
    min-height:28px; max-height:28px;
}
QPushButton#pcHostPersonaBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#60A5FA;
}
QPushButton#pcHostPersonaBtn[hostSelected="true"] {
    background:#FFFFFF; color:#1D4ED8; border:1px solid #93C5FD;
}
QPushButton#pcHostPersonaBtn[hostSelected="true"]:hover {
    background:#DBEAFE; color:#1E40AF; border-color:#3B82F6;
}

QFrame#pcSegGroup {
    background:#F1F5F9; border:1px solid #DCE5F0; border-radius:9px;
}
QFrame#pcSegSep {
    background:#D6E0EE; min-width:1px; max-width:1px; min-height:14px; max-height:14px; border:none;
}
QPushButton#pcGroupBtn {
    background:transparent; color:#334155; border:none; border-radius:7px;
    padding:0px 9px; font-size:12.5px; font-weight:650; min-height:26px; max-height:26px;
}
QPushButton#pcGroupBtn:hover {
    background:#FFFFFF; color:#1D4ED8;
}
QPushButton#pcGroupBtn:disabled {
    background:transparent; color:#94A3B8;
}

QFrame#pcFontCapsule {
    background:#F1F5F9; border:1px solid #DCE5F0; border-radius:9px;
}
QPushButton#pcFontStepBtn {
    background:transparent; color:#475569; border:none; border-radius:6px;
    padding:0px 4px; font-size:11.5px; font-weight:800;
    min-width:24px; max-width:26px; min-height:24px; max-height:24px;
}
QPushButton#pcFontStepBtn:hover {
    background:#FFFFFF; color:#1D4ED8;
}
QSlider#pcFontSlider { min-height:20px; background:transparent; }
QSlider#pcFontSlider::groove:horizontal { height:4px; background:#CBD5E1; border-radius:2px; }
QSlider#pcFontSlider::sub-page:horizontal { background:#2F6FED; border-radius:2px; }
QSlider#pcFontSlider::handle:horizontal {
    background:#2F6FED; border:2px solid #FFFFFF; width:12px; height:12px;
    margin:-4px 0; border-radius:6px;
}

QPushButton#pcHelpBtn {
    min-width:26px; max-width:26px; min-height:26px; max-height:26px;
    padding:0px; border-radius:13px; font-size:12px; font-weight:800;
    background:#F1F5F9; color:#64748B; border:1px solid #DCE5F0;
}
QPushButton#pcHelpBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}

QPushButton#pcEyePill, QPushButton#pcModePill {
    min-height:24px; max-height:24px; padding:0px 8px;
    border-radius:12px; font-size:11.5px; font-weight:750;
}
QPushButton#pcEyePill[eyeState="open"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
}
QPushButton#pcEyePill[eyeState="open"]:hover {
    background:#DBEAFE; border-color:#93C5FD;
}
QPushButton#pcEyePill[eyeState="closed"] {
    background:#F5F3FF; color:#6D28D9; border:1px solid #DDD6FE;
}
QPushButton#pcEyePill[eyeState="closed"]:hover {
    background:#EDE9FE; border-color:#C4B5FD;
}
QPushButton#pcEyePill[eyeState="unclassified"] {
    background:#FFFBEB; color:#B45309; border:1px solid #FDE68A;
}
QPushButton#pcEyePill[eyeState="unclassified"]:hover {
    background:#FEF3C7; border-color:#FBBF24;
}

QPushButton#pcModePill[modeState="frame"] {
    background:#F1F5F9; color:#334155; border:1px solid #CBD5E1;
}
QPushButton#pcModePill[modeState="frame"]:hover {
    background:#E2E8F0; color:#0F172A; border-color:#94A3B8;
}
QPushButton#pcModePill[modeState="material"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QPushButton#pcModePill[modeState="material"]:hover {
    background:#D1FAE5; border-color:#6EE7B7;
}
QPushButton#pcModePill[modeState="omini"] {
    background:#7C3AED; color:#FFFFFF; border:1px solid #6D28D9;
}
QPushButton#pcModePill[modeState="omini"]:hover {
    background:#6D28D9; border-color:#5B21B6;
}

QPushButton#pcMiniToggleBtn {
    background:#F1F5F9; color:#475569; border:1px solid #DCE4EF;
    border-radius:6px; padding:2px 8px; font-size:11.5px; font-weight:700;
    min-height:22px; max-height:22px;
}
QPushButton#pcMiniToggleBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE;
}
QPushButton#pcMiniToggleBtn:checked {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #93C5FD;
}

QTableWidget#promptTaskTable {
    gridline-color:#EDF2F8;
}
'''

DARK += r'''
QFrame#hostCard {
    background:#1D242E; border:1px solid #34404E; border-radius:12px;
}
QFrame#hostCard:hover {
    background:#222C3A; border:1.5px solid #4B6EA8;
}
QFrame#hostCard[selected="true"] {
    background:#1D304B; border:2px solid #4B82F1;
}
QFrame#hostCard[selected="true"]:hover {
    background:#213756; border:2px solid #60A5FA;
}
QLabel#miniTagSubmitted {
    background:#163829; color:#6EE7B7; border:1px solid #286448;
    border-radius:8px; padding:1px 6px; font-size:11px; font-weight:800;
}
QPushButton#pcHostPersonaBtn {
    background:#263142; color:#E2E8F0; border:1px solid #3D4D63;
    border-radius:8px; padding:0px 10px; font-size:12.5px; font-weight:750;
    min-height:28px; max-height:28px;
}
QPushButton#pcHostPersonaBtn:hover {
    background:#2F3F56; color:#93C5FD; border-color:#60A5FA;
}
QPushButton#pcHostPersonaBtn[hostSelected="true"] {
    background:#253C5E; color:#BFDBFE; border:1px solid #4B82F1;
}
QPushButton#pcHostPersonaBtn[hostSelected="true"]:hover {
    background:#2E4B75; color:#DBEAFE; border-color:#60A5FA;
}

QFrame#pcSegGroup {
    background:#222B38; border:1px solid #364355; border-radius:9px;
}
QFrame#pcSegSep {
    background:#364355; min-width:1px; max-width:1px; min-height:14px; max-height:14px; border:none;
}
QPushButton#pcGroupBtn {
    background:transparent; color:#CBD5E1; border:none; border-radius:7px;
    padding:0px 9px; font-size:12.5px; font-weight:650; min-height:26px; max-height:26px;
}
QPushButton#pcGroupBtn:hover {
    background:#2E3B4E; color:#93C5FD;
}
QPushButton#pcGroupBtn:disabled {
    background:transparent; color:#5E6B7E;
}

QFrame#pcFontCapsule {
    background:#222B38; border:1px solid #364355; border-radius:9px;
}
QPushButton#pcFontStepBtn {
    background:transparent; color:#CBD5E1; border:none; border-radius:6px;
    padding:0px 4px; font-size:11.5px; font-weight:800;
    min-width:24px; max-width:26px; min-height:24px; max-height:24px;
}
QPushButton#pcFontStepBtn:hover {
    background:#2E3B4E; color:#93C5FD;
}
QSlider#pcFontSlider { min-height:20px; background:transparent; }
QSlider#pcFontSlider::groove:horizontal { height:4px; background:#384659; border-radius:2px; }
QSlider#pcFontSlider::sub-page:horizontal { background:#4B82F1; border-radius:2px; }
QSlider#pcFontSlider::handle:horizontal {
    background:#60A5FA; border:2px solid #0F172A; width:12px; height:12px;
    margin:-4px 0; border-radius:6px;
}

QPushButton#pcHelpBtn {
    min-width:26px; max-width:26px; min-height:26px; max-height:26px;
    padding:0px; border-radius:13px; font-size:12px; font-weight:800;
    background:#252F3E; color:#94A3B8; border:1px solid #364355;
}
QPushButton#pcHelpBtn:hover {
    background:#1E3A5F; color:#93C5FD; border-color:#3B82F6;
}

QPushButton#pcEyePill, QPushButton#pcModePill {
    min-height:24px; max-height:24px; padding:0px 8px;
    border-radius:12px; font-size:11.5px; font-weight:750;
}
QPushButton#pcEyePill[eyeState="open"] {
    background:#1E3A64; color:#BFDBFE; border:1px solid #3B82F6;
}
QPushButton#pcEyePill[eyeState="open"]:hover {
    background:#25487B; border-color:#60A5FA;
}
QPushButton#pcEyePill[eyeState="closed"] {
    background:#34264C; color:#DDD6FE; border:1px solid #8B5CF6;
}
QPushButton#pcEyePill[eyeState="closed"]:hover {
    background:#423060; border-color:#A78BFA;
}
QPushButton#pcEyePill[eyeState="unclassified"] {
    background:#3D2F1A; color:#FCD34D; border:1px solid #D97706;
}
QPushButton#pcEyePill[eyeState="unclassified"]:hover {
    background:#4E3B20; border-color:#FBBF24;
}

QPushButton#pcModePill[modeState="frame"] {
    background:#252F3E; color:#CBD5E1; border:1px solid #3E4E63;
}
QPushButton#pcModePill[modeState="frame"]:hover {
    background:#303D50; color:#FFFFFF; border-color:#5A6E8A;
}
QPushButton#pcModePill[modeState="material"] {
    background:#163829; color:#6EE7B7; border:1px solid #22C55E;
}
QPushButton#pcModePill[modeState="material"]:hover {
    background:#1C4734; border-color:#4ADE80;
}
QPushButton#pcModePill[modeState="omini"] {
    background:#7C3AED; color:#FFFFFF; border:1px solid #6D28D9;
}
QPushButton#pcModePill[modeState="omini"]:hover {
    background:#6D28D9; border-color:#8B5CF6;
}

QPushButton#pcMiniToggleBtn {
    background:#252E3A; color:#CBD5E1; border:1px solid #384556;
    border-radius:6px; padding:2px 8px; font-size:11.5px; font-weight:700;
    min-height:22px; max-height:22px;
}
QPushButton#pcMiniToggleBtn:hover {
    background:#1E3A5F; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#pcMiniToggleBtn:checked {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6;
}

QTableWidget#promptTaskTable {
    gridline-color:#263140;
}
'''

LIGHT += r'''
/* ---- Flow 生成中心 · 生产进度重构样式 (Light) ---- */
QPushButton#flowProgFilterPill {
    background:#F1F5F9; color:#475569; border:1px solid #DCE5F0;
    border-radius:13px; padding:0px 11px; min-height:26px; max-height:26px;
    font-size:12px; font-weight:750;
}
QPushButton#flowProgFilterPill:hover {
    background:#E8F0FE; color:#1D4ED8; border-color:#BFDBFE;
}
QPushButton#flowProgFilterPill[pillKind="failed"][hasAlert="true"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QPushButton#flowProgFilterPill:checked {
    background:#2563EB; color:#FFFFFF; border:1px solid #1D4ED8;
}
QPushButton#flowProgFilterPill[pillKind="running"]:checked {
    background:#2563EB; color:#FFFFFF; border:1px solid #1D4ED8;
}
QPushButton#flowProgFilterPill[pillKind="failed"]:checked {
    background:#DC2626; color:#FFFFFF; border:1px solid #B91C1C;
}
QPushButton#flowProgFilterPill[pillKind="waiting"]:checked {
    background:#475569; color:#FFFFFF; border:1px solid #334155;
}
QPushButton#flowProgFilterPill[pillKind="done"]:checked {
    background:#059669; color:#FFFFFF; border:1px solid #047857;
}
QCheckBox#flowAutoCollapseCheck {
    color:#475569; font-size:12.5px; font-weight:700; spacing:6px; background:transparent;
}
QCheckBox#flowAutoCollapseCheck:hover {
    color:#1E293B;
}

QFrame#flowRecipientCard {
    background:#F8FAFC; border:1px solid #DFE7F2; border-radius:12px;
}
QFrame#flowRecipientCard[tone="running"] {
    background:#F7FAFF; border:1px solid #BFDBFE;
}
QFrame#flowRecipientCard[tone="prio"] {
    background:#FFFDF7; border:1px solid #FCD34D;
}
QFrame#flowRecipientCard[tone="failed"] {
    background:#FFFBFB; border:1px solid #FECACA;
}
QFrame#flowRecipientCard[tone="done"] {
    background:#F4FBF7; border:1px solid #BBF7D0;
}

QFrame#flowRecipientHead {
    background:transparent; border:none; border-bottom:1px solid #E6EEF8;
    border-top-left-radius:12px; border-top-right-radius:12px;
}
QFrame#flowRecipientHead[collapsed="true"] {
    border-bottom:none; border-radius:12px;
}
QFrame#flowRecipientHead:hover {
    background:rgba(59, 130, 246, 0.05);
}
QWidget#flowRecipientBody {
    background:transparent; border:none;
}

QLabel#flowRecAvatar {
    background:#E0ECFF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:15px; font-size:13.5px; font-weight:800;
}
QLabel#flowRecAvatar[tone="prio"] {
    background:#FEF3C7; color:#B45309; border:1px solid #FCD34D;
}
QLabel#flowRecAvatar[tone="failed"] {
    background:#FEE2E2; color:#B91C1C; border:1px solid #FECACA;
}
QLabel#flowRecAvatar[tone="done"] {
    background:#D1FAE5; color:#047857; border:1px solid #6EE7B7;
}

QLabel#flowRecName {
    color:#0F172A; font-size:14.5px; font-weight:800; background:transparent;
}
QLabel#flowRecBadge {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:10px; padding:2px 9px; font-size:11.5px; font-weight:750;
}
QLabel#flowRecBadge[tone="prio"] {
    background:#FEF3C7; color:#B45309; border:1px solid #FDE68A;
}
QLabel#flowRecBadge[tone="failed"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QLabel#flowRecBadge[tone="waiting"] {
    background:#F1F5F9; color:#475569; border:1px solid #CBD5E1;
}
QLabel#flowRecBadge[tone="done"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}

QLabel#flowRecMeta {
    color:#475569; font-size:12.5px; font-weight:650; background:transparent;
}
QProgressBar#flowRecBar {
    background:#E2E8F0; border:none; border-radius:3px; min-height:6px; max-height:6px;
}
QProgressBar#flowRecBar::chunk {
    background:#3B82F6; border-radius:3px;
}
QProgressBar#flowRecBar[tone="prio"]::chunk { background:#F59E0B; }
QProgressBar#flowRecBar[tone="failed"]::chunk { background:#EF4444; }
QProgressBar#flowRecBar[tone="waiting"]::chunk { background:#64748B; }
QProgressBar#flowRecBar[tone="done"]::chunk { background:#10B981; }

QLabel#flowRecPct {
    color:#1E293B; font-size:12.5px; font-weight:800; background:transparent;
}
QLabel#flowRecPct[tone="done"] { color:#047857; }
QLabel#flowRecPct[tone="running"] { color:#1D4ED8; }
QLabel#flowRecPct[tone="prio"] { color:#B45309; }
QLabel#flowRecPct[tone="failed"] { color:#DC2626; }

QLabel#flowRecChevron {
    background:#EDF2F9; color:#475569; border:1px solid #DCE5F2;
    border-radius:7px; padding:0px 8px; font-size:11.5px; font-weight:750;
}

QFrame#flowHostCard {
    background:#FFFFFF; border:1px solid #E2E8F0; border-radius:11px;
}
QFrame#flowHostCard:hover {
    border-color:#93C5FD;
}
QFrame#flowHostCard[tone="prio"] {
    background:#FFFEFA; border:1.5px solid #F59E0B;
}
QFrame#flowHostCard[tone="running"] {
    background:#FAFCFF; border:1.5px solid #60A5FA;
}
QFrame#flowHostCard[tone="failed"] {
    background:#FFFBFB; border:1.5px solid #FCA5A5;
}
QFrame#flowHostCard[tone="paused"] {
    background:#F8FAFC; border:1px dashed #94A3B8;
}
QFrame#flowHostCard[tone="done"] {
    background:#F7FCFA; border:1px solid #A7F3D0;
}

QLabel#flowHostThumb {
    background:#EEF2F7; color:#94A3B8; border:1px solid #E2E8F0;
    border-radius:7px; font-size:11px; font-weight:650;
}
QLabel#flowHostTitle {
    color:#0F172A; font-size:13.5px; font-weight:800; background:transparent;
}
QLabel#flowHostDoneBadge {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
    border-radius:10px; padding:2px 8px; font-size:11px; font-weight:800;
}

QPushButton#flowHostPrioBtn {
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1;
    border-radius:7px; padding:0px 9px; min-height:24px; max-height:24px;
    font-size:11.5px; font-weight:750;
}
QPushButton#flowHostPrioBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}
QPushButton#flowHostPrioBtn[active="true"] {
    background:#F59E0B; color:#FFFFFF; border:1px solid #D97706; font-weight:800;
}
QPushButton#flowHostPrioBtn[active="true"]:hover {
    background:#D97706; border-color:#B45309;
}

QLabel#flowHostVideoMeta {
    color:#1E293B; font-size:12px; font-weight:750; background:transparent;
}
QLabel#flowHostSegMeta {
    color:#64748B; font-size:11.5px; font-weight:650; background:transparent;
}

QProgressBar#flowHostBar {
    background:#E8EEF6; border:none; border-radius:3px; min-height:6px; max-height:6px;
}
QProgressBar#flowHostBar::chunk {
    background:#3B82F6; border-radius:3px;
}
QProgressBar#flowHostBar[tone="prio"]::chunk { background:#F59E0B; }
QProgressBar#flowHostBar[tone="running"]::chunk { background:#2563EB; }
QProgressBar#flowHostBar[tone="failed"]::chunk { background:#EF4444; }
QProgressBar#flowHostBar[tone="paused"]::chunk { background:#94A3B8; }
QProgressBar#flowHostBar[tone="waiting"]::chunk { background:#64748B; }
QProgressBar#flowHostBar[tone="done"]::chunk { background:#10B981; }

QLabel#flowHostState {
    color:#64748B; font-size:11.5px; font-weight:700; background:transparent;
}
QLabel#flowHostState[tone="running"] { color:#1D4ED8; }
QLabel#flowHostState[tone="prio"] { color:#B45309; }
QLabel#flowHostState[tone="failed"] { color:#DC2626; }
QLabel#flowHostState[tone="paused"] { color:#B45309; }
QLabel#flowHostState[tone="done"] { color:#059669; }

QLabel#flowMonitorEmpty {
    color:#64748B; font-size:13px; font-weight:650;
    background:#F8FAFC; border:1px dashed #CBD5E1; border-radius:10px; padding:24px;
}
'''

DARK += r'''
/* ---- Flow 生成中心 · 生产进度重构样式 (Dark) ---- */
QPushButton#flowProgFilterPill {
    background:#212A36; color:#94A3B8; border:1px solid #334155;
    border-radius:13px; padding:0px 11px; min-height:26px; max-height:26px;
    font-size:12px; font-weight:750;
}
QPushButton#flowProgFilterPill:hover {
    background:#1E3250; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#flowProgFilterPill[pillKind="failed"][hasAlert="true"] {
    background:#3B1C22; color:#FCA5A5; border:1px solid #991B1B;
}
QPushButton#flowProgFilterPill:checked {
    background:#2563EB; color:#FFFFFF; border:1px solid #3B82F6;
}
QPushButton#flowProgFilterPill[pillKind="running"]:checked {
    background:#2563EB; color:#FFFFFF; border:1px solid #60A5FA;
}
QPushButton#flowProgFilterPill[pillKind="failed"]:checked {
    background:#DC2626; color:#FFFFFF; border:1px solid #EF4444;
}
QPushButton#flowProgFilterPill[pillKind="waiting"]:checked {
    background:#475569; color:#FFFFFF; border:1px solid #64748B;
}
QPushButton#flowProgFilterPill[pillKind="done"]:checked {
    background:#059669; color:#FFFFFF; border:1px solid #10B981;
}
QCheckBox#flowAutoCollapseCheck {
    color:#94A3B8; font-size:12.5px; font-weight:700; spacing:6px; background:transparent;
}
QCheckBox#flowAutoCollapseCheck:hover {
    color:#E2E8F0;
}

QFrame#flowRecipientCard {
    background:#19212C; border:1px solid #2D394A; border-radius:12px;
}
QFrame#flowRecipientCard[tone="running"] {
    background:#172233; border:1px solid #2A4B7C;
}
QFrame#flowRecipientCard[tone="prio"] {
    background:#231F16; border:1px solid #855916;
}
QFrame#flowRecipientCard[tone="failed"] {
    background:#261A1E; border:1px solid #7F262E;
}
QFrame#flowRecipientCard[tone="done"] {
    background:#16241F; border:1px solid #21513B;
}

QFrame#flowRecipientHead {
    background:transparent; border:none; border-bottom:1px solid #263242;
    border-top-left-radius:12px; border-top-right-radius:12px;
}
QFrame#flowRecipientHead[collapsed="true"] {
    border-bottom:none; border-radius:12px;
}
QFrame#flowRecipientHead:hover {
    background:rgba(96, 165, 250, 0.07);
}
QWidget#flowRecipientBody {
    background:transparent; border:none;
}

QLabel#flowRecAvatar {
    background:#1E3354; color:#93C5FD; border:1px solid #2F5285;
    border-radius:15px; font-size:13.5px; font-weight:800;
}
QLabel#flowRecAvatar[tone="prio"] {
    background:#3D2E14; color:#FCD34D; border:1px solid #926217;
}
QLabel#flowRecAvatar[tone="failed"] {
    background:#421E24; color:#FCA5A5; border:1px solid #8C2B36;
}
QLabel#flowRecAvatar[tone="done"] {
    background:#183B2C; color:#6EE7B7; border:1px solid #276749;
}

QLabel#flowRecName {
    color:#F1F5F9; font-size:14.5px; font-weight:800; background:transparent;
}
QLabel#flowRecBadge {
    background:#1D3251; color:#93C5FD; border:1px solid #2E5082;
    border-radius:10px; padding:2px 9px; font-size:11.5px; font-weight:750;
}
QLabel#flowRecBadge[tone="prio"] {
    background:#3B2C14; color:#FCD34D; border:1px solid #855A18;
}
QLabel#flowRecBadge[tone="failed"] {
    background:#3D1D23; color:#FCA5A5; border:1px solid #8A2A35;
}
QLabel#flowRecBadge[tone="waiting"] {
    background:#242E3C; color:#94A3B8; border:1px solid #38465A;
}
QLabel#flowRecBadge[tone="done"] {
    background:#163829; color:#6EE7B7; border:1px solid #235D43;
}

QLabel#flowRecMeta {
    color:#94A3B8; font-size:12.5px; font-weight:650; background:transparent;
}
QProgressBar#flowRecBar {
    background:#283445; border:none; border-radius:3px; min-height:6px; max-height:6px;
}
QProgressBar#flowRecBar::chunk {
    background:#3B82F6; border-radius:3px;
}
QProgressBar#flowRecBar[tone="prio"]::chunk { background:#F59E0B; }
QProgressBar#flowRecBar[tone="failed"]::chunk { background:#EF4444; }
QProgressBar#flowRecBar[tone="waiting"]::chunk { background:#64748B; }
QProgressBar#flowRecBar[tone="done"]::chunk { background:#10B981; }

QLabel#flowRecPct {
    color:#E2E8F0; font-size:12.5px; font-weight:800; background:transparent;
}
QLabel#flowRecPct[tone="done"] { color:#6EE7B7; }
QLabel#flowRecPct[tone="running"] { color:#93C5FD; }
QLabel#flowRecPct[tone="prio"] { color:#FCD34D; }
QLabel#flowRecPct[tone="failed"] { color:#FCA5A5; }

QLabel#flowRecChevron {
    background:#242F3E; color:#94A3B8; border:1px solid #354356;
    border-radius:7px; padding:0px 8px; font-size:11.5px; font-weight:750;
}

QFrame#flowHostCard {
    background:#202937; border:1px solid #313E50; border-radius:11px;
}
QFrame#flowHostCard:hover {
    border-color:#4B82F1;
}
QFrame#flowHostCard[tone="prio"] {
    background:#282218; border:1.5px solid #D97706;
}
QFrame#flowHostCard[tone="running"] {
    background:#1C293D; border:1.5px solid #3B82F6;
}
QFrame#flowHostCard[tone="failed"] {
    background:#2A1D22; border:1.5px solid #EF4444;
}
QFrame#flowHostCard[tone="paused"] {
    background:#1E2632; border:1px dashed #64748B;
}
QFrame#flowHostCard[tone="done"] {
    background:#192923; border:1px solid #245A42;
}

QLabel#flowHostThumb {
    background:#161E29; color:#64748B; border:1px solid #2D394A;
    border-radius:7px; font-size:11px; font-weight:650;
}
QLabel#flowHostTitle {
    color:#F1F5F9; font-size:13.5px; font-weight:800; background:transparent;
}
QLabel#flowHostDoneBadge {
    background:#163829; color:#6EE7B7; border:1px solid #245D43;
    border-radius:10px; padding:2px 8px; font-size:11px; font-weight:800;
}

QPushButton#flowHostPrioBtn {
    background:#273242; color:#CBD5E1; border:1px solid #3B4A5E;
    border-radius:7px; padding:0px 9px; min-height:24px; max-height:24px;
    font-size:11.5px; font-weight:750;
}
QPushButton#flowHostPrioBtn:hover {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#flowHostPrioBtn[active="true"] {
    background:#D97706; color:#FFFFFF; border:1px solid #F59E0B; font-weight:800;
}
QPushButton#flowHostPrioBtn[active="true"]:hover {
    background:#B45309; border-color:#FBBF24;
}

QLabel#flowHostVideoMeta {
    color:#E2E8F0; font-size:12px; font-weight:750; background:transparent;
}
QLabel#flowHostSegMeta {
    color:#94A3B8; font-size:11.5px; font-weight:650; background:transparent;
}

QProgressBar#flowHostBar {
    background:#2A3647; border:none; border-radius:3px; min-height:6px; max-height:6px;
}
QProgressBar#flowHostBar::chunk {
    background:#3B82F6; border-radius:3px;
}
QProgressBar#flowHostBar[tone="prio"]::chunk { background:#F59E0B; }
QProgressBar#flowHostBar[tone="running"]::chunk { background:#3B82F6; }
QProgressBar#flowHostBar[tone="failed"]::chunk { background:#EF4444; }
QProgressBar#flowHostBar[tone="paused"]::chunk { background:#64748B; }
QProgressBar#flowHostBar[tone="waiting"]::chunk { background:#64748B; }
QProgressBar#flowHostBar[tone="done"]::chunk { background:#10B981; }

QLabel#flowHostState {
    color:#94A3B8; font-size:11.5px; font-weight:700; background:transparent;
}
QLabel#flowHostState[tone="running"] { color:#93C5FD; }
QLabel#flowHostState[tone="prio"] { color:#FCD34D; }
QLabel#flowHostState[tone="failed"] { color:#FCA5A5; }
QLabel#flowHostState[tone="paused"] { color:#FCD34D; }
QLabel#flowHostState[tone="done"] { color:#6EE7B7; }

QLabel#flowMonitorEmpty {
    color:#94A3B8; font-size:13px; font-weight:650;
    background:#1B232F; border:1px dashed #334155; border-radius:10px; padding:24px;
}
'''

LIGHT += r'''
/* ---- 自动剪辑中心 · 今日剪辑进度重构样式 (Light) ---- */
QPushButton#flowProgFilterPill[pillKind="ready"]:checked {
    background:#0284C7; color:#FFFFFF; border:1px solid #0369A1;
}
QFrame#flowHostCard[tone="ready"] {
    background:#F8FCFF; border:1.5px solid #7DD3FC;
}
QProgressBar#flowHostBar[tone="ready"]::chunk { background:#0EA5E9; }
QLabel#flowHostState[tone="ready"] { color:#0369A1; }

QFrame#dvViewSwitchWrap {
    background:#EDF2F8; border:1px solid #D5E0EE; border-radius:8px;
}
QPushButton#dvViewSwitchBtn {
    background:transparent; color:#475569; border:none;
    border-radius:6px; padding:0px 9px; min-height:24px; max-height:24px;
    font-size:11.5px; font-weight:750;
}
QPushButton#dvViewSwitchBtn:hover {
    color:#1E293B; background:rgba(255,255,255,0.55);
}
QPushButton#dvViewSwitchBtn:checked {
    background:#FFFFFF; color:#1D4ED8; border:1px solid #CBD5E1; font-weight:800;
}

QLabel#dvHostStatusBadge {
    background:#F1F5F9; color:#475569; border:1px solid #CBD5E1;
    border-radius:9px; padding:1px 7px; font-size:11px; font-weight:800;
}
QLabel#dvHostStatusBadge[tone="done"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QLabel#dvHostStatusBadge[tone="prio"] {
    background:#FEF3C7; color:#B45309; border:1px solid #FDE68A;
}
QLabel#dvHostStatusBadge[tone="running"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
}
QLabel#dvHostStatusBadge[tone="ready"] {
    background:#E0F2FE; color:#0369A1; border:1px solid #BAE6FD;
}
QLabel#dvHostStatusBadge[tone="failed"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}

QLabel#dvHostTagPill {
    background:#F1F5F9; color:#475569; border:1px solid #E2E8F0;
    border-radius:6px; padding:0px 5px; font-size:10.5px; font-weight:750;
}
QLabel#dvHostTagPill[kind="wm"] {
    background:#ECFEFF; color:#0E7490; border:1px solid #A5F3FC;
}
QLabel#dvHostTagPill[kind="ratio"] {
    background:#F3E8FF; color:#6D28D9; border:1px solid #DDD6FE;
}

QPushButton#dvHostMiniBtn {
    background:#F8FAFC; color:#475569; border:1px solid #D5E0EE;
    border-radius:6px; padding:0px 7px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dvHostMiniBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}
QPushButton#dvHostMiniBtn[active="true"] {
    background:#EFF6FF; color:#1D4ED8; border-color:#60A5FA; font-weight:800;
}

QFrame#dvHostDrawer {
    background:transparent; border:none; border-top:1px solid #E5EDF6;
}
QScrollArea#dvDrawerScroll {
    background:transparent; border:none;
}
QWidget#dvDrawerContent {
    background:transparent; border:none;
}
QFrame#dvVideoRow {
    background:#F8FAFC; border:1px solid #E6EEF8; border-radius:6px;
}
QFrame#dvVideoRow:hover {
    background:#EFF6FF; border-color:#BFDBFE;
}
QLabel#dvVidSeq {
    color:#334155; font-size:11px; font-weight:800; background:transparent;
}
QLabel#dvVidSeg {
    color:#64748B; font-size:11px; font-weight:700; background:transparent;
}
QLabel#dvVidSeg[ready="true"] {
    color:#059669;
}
QLabel#dvVidStatus {
    color:#475569; font-size:11px; font-weight:800; background:transparent;
}
QLabel#dvVidStatus[tone="done"] { color:#059669; }
QLabel#dvVidStatus[tone="prio"] { color:#D97706; }
QLabel#dvVidStatus[tone="running"] { color:#2563EB; }
QLabel#dvVidStatus[tone="ready"] { color:#0284C7; }
QLabel#dvVidStatus[tone="failed"] { color:#DC2626; }
QLabel#dvVidPath {
    color:#475569; font-size:11px; font-weight:600; background:transparent;
}
'''

DARK += r'''
/* ---- 自动剪辑中心 · 今日剪辑进度重构样式 (Dark) ---- */
QPushButton#flowProgFilterPill[pillKind="ready"]:checked {
    background:#0284C7; color:#FFFFFF; border:1px solid #38BDF8;
}
QFrame#flowHostCard[tone="ready"] {
    background:#192635; border:1.5px solid #0284C7;
}
QProgressBar#flowHostBar[tone="ready"]::chunk { background:#38BDF8; }
QLabel#flowHostState[tone="ready"] { color:#7DD3FC; }

QFrame#dvViewSwitchWrap {
    background:#1C2430; border:1px solid #313E50; border-radius:8px;
}
QPushButton#dvViewSwitchBtn {
    background:transparent; color:#94A3B8; border:none;
    border-radius:6px; padding:0px 9px; min-height:24px; max-height:24px;
    font-size:11.5px; font-weight:750;
}
QPushButton#dvViewSwitchBtn:hover {
    color:#E2E8F0; background:rgba(255,255,255,0.05);
}
QPushButton#dvViewSwitchBtn:checked {
    background:#2B394D; color:#93C5FD; border:1px solid #415572; font-weight:800;
}

QLabel#dvHostStatusBadge {
    background:#242E3C; color:#94A3B8; border:1px solid #38465A;
    border-radius:9px; padding:1px 7px; font-size:11px; font-weight:800;
}
QLabel#dvHostStatusBadge[tone="done"] {
    background:#163829; color:#6EE7B7; border:1px solid #245D43;
}
QLabel#dvHostStatusBadge[tone="prio"] {
    background:#3B2C14; color:#FCD34D; border:1px solid #855A18;
}
QLabel#dvHostStatusBadge[tone="running"] {
    background:#1D3251; color:#93C5FD; border:1px solid #2E5082;
}
QLabel#dvHostStatusBadge[tone="ready"] {
    background:#163047; color:#7DD3FC; border:1px solid #1E4E75;
}
QLabel#dvHostStatusBadge[tone="failed"] {
    background:#3D1D23; color:#FCA5A5; border:1px solid #8A2A35;
}

QLabel#dvHostTagPill {
    background:#242E3C; color:#94A3B8; border:1px solid #354356;
    border-radius:6px; padding:0px 5px; font-size:10.5px; font-weight:750;
}
QLabel#dvHostTagPill[kind="wm"] {
    background:#14323B; color:#67E8F9; border:1px solid #1E5463;
}
QLabel#dvHostTagPill[kind="ratio"] {
    background:#2B1F42; color:#C4B5FD; border:1px solid #4C3575;
}

QPushButton#dvHostMiniBtn {
    background:#253040; color:#CBD5E1; border:1px solid #38475B;
    border-radius:6px; padding:0px 7px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dvHostMiniBtn:hover {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#dvHostMiniBtn[active="true"] {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6; font-weight:800;
}

QFrame#dvHostDrawer {
    background:transparent; border:none; border-top:1px solid #2D394A;
}
QScrollArea#dvDrawerScroll {
    background:transparent; border:none;
}
QWidget#dvDrawerContent {
    background:transparent; border:none;
}
QFrame#dvVideoRow {
    background:#18202B; border:1px solid #283445; border-radius:6px;
}
QFrame#dvVideoRow:hover {
    background:#1E2C3F; border-color:#3B82F6;
}
QLabel#dvVidSeq {
    color:#E2E8F0; font-size:11px; font-weight:800; background:transparent;
}
QLabel#dvVidSeg {
    color:#94A3B8; font-size:11px; font-weight:700; background:transparent;
}
QLabel#dvVidSeg[ready="true"] {
    color:#6EE7B7;
}
QLabel#dvVidStatus {
    color:#94A3B8; font-size:11px; font-weight:800; background:transparent;
}
QLabel#dvVidStatus[tone="done"] { color:#6EE7B7; }
QLabel#dvVidStatus[tone="prio"] { color:#FCD34D; }
QLabel#dvVidStatus[tone="running"] { color:#93C5FD; }
QLabel#dvVidStatus[tone="ready"] { color:#7DD3FC; }
QLabel#dvVidStatus[tone="failed"] { color:#FCA5A5; }
QLabel#dvVidPath {
    color:#94A3B8; font-size:11px; font-weight:600; background:transparent;
}
'''

LIGHT += r'''
/* ---- Flow 生成中心 · 下载完成管理窗口样式 (Light) ---- */
QFrame#flowHostCard[expanded="true"] {
    background:#EFF6FF; border:2px solid #2563EB;
}
QFrame#flowHostCard[checkedState="full"] {
    border:1.5px solid #10B981; background:#F0FDF4;
}
QFrame#flowHostCard[expanded="true"][checkedState="full"] {
    border:2px solid #2563EB; background:#EFF6FF;
}
QPushButton#dlHostMiniBtn {
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1;
    border-radius:7px; padding:0px 8px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dlHostMiniBtn[iconOnly="true"] {
    padding:0px; min-width:26px; max-width:26px; min-height:22px; max-height:22px;
    font-size:12px; font-weight:800;
}
QPushButton#dlHostMiniBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}
QPushButton#dlHostMiniBtn[active="true"] {
    background:#DBEAFE; color:#1D4ED8; border:1px solid #60A5FA; font-weight:800;
}
QPushButton#dlHostMiniBtn[kind="redl"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QPushButton#dlHostMiniBtn[kind="redl"]:hover {
    background:#D1FAE5; color:#065F46; border-color:#6EE7B7;
}
QPushButton#dlHostMiniBtn[kind="import"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
}
QPushButton#dlHostMiniBtn[kind="import"]:hover {
    background:#DBEAFE; color:#1E40AF; border-color:#60A5FA;
}
QPushButton#dlIconBtn {
    background:#FFFFFF; color:#334155; border:1px solid #CBD5E1;
    border-radius:8px; padding:0px; min-width:32px; max-width:32px; min-height:28px; max-height:28px;
    font-size:13px; font-weight:750;
}
QPushButton#dlIconBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}
QLabel#flowHostSegMeta[tone="done"] { color:#059669; font-weight:800; }
QLabel#flowHostSegMeta[tone="failed"] { color:#DC2626; font-weight:800; }
QLabel#flowHostSegMeta[tone="running"] { color:#2563EB; font-weight:800; }
QFrame#dlHostDrawer {
    background:#FFFFFF; border:1.5px solid #BFDBFE; border-radius:10px;
}
QFrame#dlHostDrawerHead {
    background:#F1F6FF; border:none; border-bottom:1px solid #DBEAFE;
    border-top-left-radius:9px; border-top-right-radius:9px;
}
QLabel#dlHostDrawerTitle {
    color:#1E3A8A; font-size:12.5px; font-weight:800; background:transparent;
}
QFrame#dlVideoGroup {
    background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px;
}
QFrame#dlVideoHead {
    background:#F1F5F9; border:none; border-bottom:1px solid #E2E8F0;
    border-top-left-radius:7px; border-top-right-radius:7px;
}
QLabel#dlVideoTitle {
    color:#0F172A; font-size:12px; font-weight:800; background:transparent;
}
QFrame#dlSegRow {
    background:#FFFFFF; border:none; border-bottom:1px solid #F1F5F9;
}
QFrame#dlSegRow:hover {
    background:#F8FAFF;
}
QFrame#dlSegRow[checked="true"] {
    background:#EFF6FF;
}
QLabel#dlSegCode {
    background:#EEF2FF; color:#3730A3; border:1px solid #C7D2FE;
    border-radius:5px; padding:1px 6px; font-size:11px; font-weight:800;
}
QLabel#dlSegCode[tone="done"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QLabel#dlSegCode[tone="failed"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QLabel#dlSegFile {
    color:#1E293B; font-size:12px; font-weight:650; background:transparent;
}
QLabel#dlChip {
    background:#F1F5F9; color:#475569; border:1px solid #CBD5E1;
    border-radius:6px; padding:1px 6px; font-size:10.5px; font-weight:750;
}
QLabel#dlChip[iconOnly="true"] {
    padding:0px; min-width:22px; max-width:22px; min-height:20px; max-height:20px;
    font-size:11px; font-weight:800;
}
QLabel#dlChip[tone="done"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QLabel#dlChip[tone="warn"] {
    background:#FFFBEB; color:#B45309; border:1px solid #FDE68A;
}
QLabel#dlChip[tone="failed"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QLabel#dlSegStatus {
    color:#059669; font-size:11.5px; font-weight:750; background:transparent;
}
QLabel#dlSegStatus[tone="missing"] { color:#DC2626; font-weight:800; }
QLabel#dlSegStatus[tone="running"] { color:#2563EB; font-weight:800; }
QLabel#dlSegStatus[tone="muted"] { color:#64748B; }
'''

DARK += r'''
/* ---- Flow 生成中心 · 下载完成管理窗口样式 (Dark) ---- */
QFrame#flowHostCard[expanded="true"] {
    background:#17253B; border:2px solid #3B82F6;
}
QFrame#flowHostCard[checkedState="full"] {
    border:1.5px solid #10B981; background:#142921;
}
QFrame#flowHostCard[expanded="true"][checkedState="full"] {
    border:2px solid #3B82F6; background:#17253B;
}
QPushButton#dlHostMiniBtn {
    background:#242E3C; color:#CBD5E1; border:1px solid #38475B;
    border-radius:7px; padding:0px 8px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dlHostMiniBtn[iconOnly="true"] {
    padding:0px; min-width:26px; max-width:26px; min-height:22px; max-height:22px;
    font-size:12px; font-weight:800;
}
QPushButton#dlHostMiniBtn:hover {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#dlHostMiniBtn[active="true"] {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6; font-weight:800;
}
QPushButton#dlHostMiniBtn[kind="redl"] {
    background:#163327; color:#6EE7B7; border:1px solid #23533D;
}
QPushButton#dlHostMiniBtn[kind="redl"]:hover {
    background:#1A4232; color:#A7F3D0; border-color:#34D399;
}
QPushButton#dlHostMiniBtn[kind="import"] {
    background:#1B3150; color:#93C5FD; border:1px solid #2E5284;
}
QPushButton#dlHostMiniBtn[kind="import"]:hover {
    background:#23406A; color:#BFDBFE; border-color:#60A5FA;
}
QPushButton#dlIconBtn {
    background:#1E293B; color:#CBD5E1; border:1px solid #334155;
    border-radius:8px; padding:0px; min-width:32px; max-width:32px; min-height:28px; max-height:28px;
    font-size:13px; font-weight:750;
}
QPushButton#dlIconBtn:hover {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6;
}
QLabel#flowHostSegMeta[tone="done"] { color:#6EE7B7; font-weight:800; }
QLabel#flowHostSegMeta[tone="failed"] { color:#FCA5A5; font-weight:800; }
QLabel#flowHostSegMeta[tone="running"] { color:#93C5FD; font-weight:800; }
QFrame#dlHostDrawer {
    background:#161E29; border:1.5px solid #2E5082; border-radius:10px;
}
QFrame#dlHostDrawerHead {
    background:#1B283B; border:none; border-bottom:1px solid #2B3E59;
    border-top-left-radius:9px; border-top-right-radius:9px;
}
QLabel#dlHostDrawerTitle {
    color:#93C5FD; font-size:12.5px; font-weight:800; background:transparent;
}
QFrame#dlVideoGroup {
    background:#1B2430; border:1px solid #2A3647; border-radius:8px;
}
QFrame#dlVideoHead {
    background:#212C3B; border:none; border-bottom:1px solid #2D3B4E;
    border-top-left-radius:7px; border-top-right-radius:7px;
}
QLabel#dlVideoTitle {
    color:#E2E8F0; font-size:12px; font-weight:800; background:transparent;
}
QFrame#dlSegRow {
    background:#161E29; border:none; border-bottom:1px solid #212C3B;
}
QFrame#dlSegRow:hover {
    background:#1D2837;
}
QFrame#dlSegRow[checked="true"] {
    background:#1B2E4B;
}
QLabel#dlSegCode {
    background:#232A47; color:#A5B4FC; border:1px solid #3B4675;
    border-radius:5px; padding:1px 6px; font-size:11px; font-weight:800;
}
QLabel#dlSegCode[tone="done"] {
    background:#163327; color:#6EE7B7; border:1px solid #23533D;
}
QLabel#dlSegCode[tone="failed"] {
    background:#3D1D23; color:#FCA5A5; border:1px solid #8A2A35;
}
QLabel#dlSegFile {
    color:#E2E8F0; font-size:12px; font-weight:650; background:transparent;
}
QLabel#dlChip {
    background:#242E3C; color:#94A3B8; border:1px solid #354356;
    border-radius:6px; padding:1px 6px; font-size:10.5px; font-weight:750;
}
QLabel#dlChip[iconOnly="true"] {
    padding:0px; min-width:22px; max-width:22px; min-height:20px; max-height:20px;
    font-size:11px; font-weight:800;
}
QLabel#dlChip[tone="done"] {
    background:#163327; color:#6EE7B7; border:1px solid #23533D;
}
QLabel#dlChip[tone="warn"] {
    background:#3B2C16; color:#FCD34D; border:1px solid #5E4624;
}
QLabel#dlChip[tone="failed"] {
    background:#3D1D23; color:#FCA5A5; border:1px solid #8A2A35;
}
QLabel#dlSegStatus {
    color:#6EE7B7; font-size:11.5px; font-weight:750; background:transparent;
}
QLabel#dlSegStatus[tone="missing"] { color:#FCA5A5; font-weight:800; }
QLabel#dlSegStatus[tone="running"] { color:#93C5FD; font-weight:800; }
QLabel#dlSegStatus[tone="muted"] { color:#94A3B8; }
'''

LIGHT += r'''
/* ---- Flow 生成中心 · 顶部状态胶条与「运行任务与异常重试」样式 (Light) ---- */
QPushButton#statRunningBtn {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statRunningBtn:hover { background:#DBEAFE; border-color:#93C5FD; }
QPushButton#statFailedBtn {
    background:#FEF2F2; color:#B91C1C; border:1px solid #FECACA;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statFailedBtn:hover { background:#FEE2E2; border-color:#FCA5A5; }
QPushButton#statFailedBtn[zero="true"] {
    background:#F8FAFC; color:#64748B; border:1px solid #E2E8F0;
}
QPushButton#statFailedBtn[zero="true"]:hover {
    background:#F1F5F9; border-color:#CBD5E1; color:#334155;
}

QPushButton#rtQuickSelectBtn {
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1;
    border-radius:8px; padding:4px 10px; min-height:26px; font-size:12px; font-weight:750;
}
QPushButton#rtQuickSelectBtn:hover { background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD; }
QPushButton#rtQuickSelectBtn[accent="amber"] {
    background:#FFFBEB; color:#B45309; border:1px solid #FCD34D;
}
QPushButton#rtQuickSelectBtn[accent="amber"]:hover {
    background:#FEF3C7; color:#92400E; border-color:#F59E0B;
}
QPushButton#rtQuickSelectBtn[accent="red"] {
    background:#FEF2F2; color:#B91C1C; border:1px solid #FECACA;
}
QPushButton#rtQuickSelectBtn[accent="red"]:hover {
    background:#FEE2E2; color:#991B1B; border-color:#FCA5A5;
}
QPushButton#rtQuickSelectBtn:disabled {
    background:#F8FAFC; color:#94A3B8; border:1px solid #E2E8F0;
}

QPushButton#rtHostMiniBtn {
    background:#F8FAFC; color:#334155; border:1px solid #CBD5E1;
    border-radius:7px; padding:0px 8px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#rtHostMiniBtn[iconOnly="true"] {
    padding:0px; min-width:26px; max-width:26px; min-height:22px; max-height:22px;
    font-size:12px; font-weight:800;
}
QPushButton#rtHostMiniBtn:hover {
    background:#EFF6FF; color:#1D4ED8; border-color:#93C5FD;
}
QPushButton#rtHostMiniBtn[active="true"] {
    background:#DBEAFE; color:#1D4ED8; border:1px solid #60A5FA; font-weight:800;
}
QPushButton#rtHostMiniBtn[kind="retry"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
}
QPushButton#rtHostMiniBtn[kind="retry"]:hover {
    background:#DBEAFE; color:#1E40AF; border-color:#60A5FA;
}
QPushButton#rtHostMiniBtn[kind="import"] {
    background:#ECFDF5; color:#047857; border:1px solid #A7F3D0;
}
QPushButton#rtHostMiniBtn[kind="import"]:hover {
    background:#D1FAE5; color:#065F46; border-color:#6EE7B7;
}
QPushButton#rtHostMiniBtn[kind="warn"] {
    background:#FFFBEB; color:#B45309; border:1px solid #FDE68A;
}
QPushButton#rtHostMiniBtn[kind="warn"]:hover {
    background:#FEF3C7; color:#92400E; border-color:#F59E0B;
}
QPushButton#rtHostMiniBtn[kind="danger"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QPushButton#rtHostMiniBtn[kind="danger"]:hover {
    background:#FEE2E2; color:#991B1B; border-color:#F87171;
}
QPushButton#rtHostMiniBtn:disabled {
    background:#F8FAFC; color:#94A3B8; border:1px solid #E2E8F0;
}

QFrame#rtSegRow {
    background:#FFFFFF; border:none; border-bottom:1px solid #F1F5F9;
}
QFrame#rtSegRow:hover { background:#F8FAFF; }
QFrame#rtSegRow[tone="stalled"] { background:#FFFDF5; }
QFrame#rtSegRow[tone="failed"], QFrame#rtSegRow[tone="prompt"], QFrame#rtSegRow[tone="upload"] { background:#FFFBFB; }
QFrame#rtSegRow[checked="true"] { background:#EFF6FF; }

QLabel#rtStatusBadge {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:6px; padding:2px 8px; font-size:11px; font-weight:800;
}
QLabel#rtStatusBadge[tone="stalled"] {
    background:#FFFBEB; color:#B45309; border:1px solid #FCD34D;
}
QLabel#rtStatusBadge[tone="failed"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QLabel#rtStatusBadge[tone="prompt"] {
    background:#FDF4FF; color:#A21CAF; border:1px solid #F0ABFC;
}
QLabel#rtStatusBadge[tone="upload"] {
    background:#FFF7ED; color:#C2410C; border:1px solid #FDBA74;
}
QLabel#rtStatusBadge[tone="queued"] {
    background:#ECFEFF; color:#0E7490; border:1px solid #A5F3FC;
}
QLabel#rtStatusBadge[tone="running"] {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
}

QComboBox#rtChannelCombo {
    background:#F8FAFC; color:#1E293B; border:1px solid #CBD5E1;
    border-radius:6px; padding:1px 6px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QComboBox#rtChannelCombo:hover { border-color:#60A5FA; background:#EFF6FF; }

QPushButton#rtDangerBtn {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
    border-radius:9px; padding:6px 14px; font-weight:750;
}
QPushButton#rtDangerBtn:hover { background:#FEE2E2; border-color:#F87171; color:#991B1B; }
QPushButton#rtDangerBtn:disabled { background:#F8FAFC; color:#94A3B8; border-color:#E2E8F0; }

/* ---- 自动剪辑中文错误提示 + 「查看详情」迷你按钮与诊断弹窗 (Light) ---- */
QLabel#cardMeta[isError="true"],
QLabel#tcGuideHint[isError="true"],
QLabel#muted[isError="true"] {
    color:#DC2626; font-weight:700;
}
QPushButton#dvErrDetailBtn {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
    border-radius:11px; padding:0px 9px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dvErrDetailBtn:hover {
    background:#FEE2E2; color:#991B1B; border-color:#F87171;
}
QPushButton#dvErrDetailBtn:pressed {
    background:#FECACA; color:#7F1D1D;
}

QScrollArea#dvErrScroll, QWidget#dvErrScrollBody {
    background:transparent; border:none;
}
QFrame#dvErrHeroCard {
    background:#FEF2F2; border:1px solid #FECACA; border-radius:12px;
}
QLabel#dvErrStageBadge {
    background:#FEE2E2; color:#B91C1C; border:1px solid #FCA5A5;
    border-radius:8px; padding:2px 9px; font-size:11px; font-weight:800;
}
QLabel#dvErrTitle {
    color:#991B1B; font-size:15px; font-weight:800;
}
QFrame#dvErrLocCard {
    background:#FFFFFF; border:1px solid #FEE2E2; border-radius:8px;
}
QLabel#dvErrLocKey {
    color:#64748B; font-size:12px; font-weight:700;
}
QLabel#dvErrLocVal {
    color:#0F172A; font-size:12px; font-weight:700;
}
QFrame#dvErrDialogCard {
    background:#FFFFFF; border:1px solid #E2E8F0; border-radius:12px;
}
QFrame#dvErrSolutionsCard {
    background:#F8FAFC; border:1px solid #BFDBFE; border-radius:12px;
}
QLabel#dvErrSectionTitle {
    color:#0F172A; font-size:13px; font-weight:800;
}
QLabel#dvErrBodyText {
    color:#334155; font-size:13px; line-height:1.5;
}
QLabel#dvErrStepBadge {
    background:#DBEAFE; color:#1D4ED8; border:1px solid #93C5FD;
    border-radius:11px; font-size:11px; font-weight:800;
}
QLabel#dvErrStepText {
    color:#1E293B; font-size:13px; font-weight:600;
}
QPushButton#dvErrRawToggleBtn {
    background:transparent; color:#64748B; border:none; padding:2px 4px;
    font-size:12px; font-weight:600; text-align:left;
}
QPushButton#dvErrRawToggleBtn:hover { color:#2563EB; }
QPlainTextEdit#dvErrRawBox {
    background:#F8FAFC; color:#475569; border:1px solid #E2E8F0;
    border-radius:8px; padding:6px 8px; font-size:11px;
    font-family:"SF Mono","Menlo","Consolas",monospace;
}

/* ---- 通用轻量确认弹窗样式 (Light) ---- */
QDialog#modernConfirmDialog {
    background:#F8FAFC;
}
QFrame#modernConfirmCard {
    background:#FFFFFF; border:1px solid #E2E8F0; border-radius:14px;
}
QFrame#modernConfirmCard[tone="danger"] {
    background:#FFFBFB; border:1px solid #FECACA;
}
QLabel#modernConfirmIcon {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:10px; font-size:17px; font-weight:800;
}
QLabel#modernConfirmIcon[tone="danger"] {
    background:#FEF2F2; color:#DC2626; border:1px solid #FECACA;
}
QLabel#modernConfirmHeadline {
    color:#0F172A; font-size:15px; font-weight:800; background:transparent;
}
QLabel#modernConfirmSub {
    color:#64748B; font-size:12.5px; font-weight:600; background:transparent;
}
QFrame#modernConfirmBullets {
    background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px;
}
QLabel#modernConfirmBulletItem {
    color:#334155; font-size:12.5px; font-weight:650; background:transparent;
}
QPushButton#modernConfirmCancelBtn {
    background:#FFFFFF; color:#475569; border:1px solid #CBD5E1;
    border-radius:9px; padding:0 16px; font-size:13px; font-weight:700;
}
QPushButton#modernConfirmCancelBtn:hover {
    background:#F1F5F9; color:#0F172A; border-color:#94A3B8;
}
QPushButton#modernConfirmExtraBtn {
    background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE;
    border-radius:9px; padding:0 16px; font-size:13px; font-weight:750;
}
QPushButton#modernConfirmExtraBtn:hover {
    background:#DBEAFE; border-color:#60A5FA;
}
QPushButton#modernConfirmOkBtn {
    background:#2563EB; color:#FFFFFF; border:none;
    border-radius:9px; padding:0 18px; font-size:13px; font-weight:800;
}
QPushButton#modernConfirmOkBtn:hover {
    background:#1D4ED8;
}
QPushButton#modernConfirmOkBtn[tone="danger"] {
    background:#DC2626; color:#FFFFFF;
}
QPushButton#modernConfirmOkBtn[tone="danger"]:hover {
    background:#B91C1C;
}
'''

DARK += r'''
/* ---- Flow 生成中心 · 顶部状态胶条与「运行任务与异常重试」样式 (Dark) ---- */
QPushButton#statRunningBtn {
    background:#1B2E4B; color:#93C5FD; border:1px solid #2E5082;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statRunningBtn:hover { background:#233B61; border-color:#3B82F6; }
QPushButton#statFailedBtn {
    background:#3B1D24; color:#FCA5A5; border:1px solid #7F2936;
    border-radius:13px; padding:5px 13px; font-size:13px; font-weight:750; min-height:26px;
}
QPushButton#statFailedBtn:hover { background:#4C222B; border-color:#EF4444; }
QPushButton#statFailedBtn[zero="true"] {
    background:#212B38; color:#94A3B8; border:1px solid #334155;
}
QPushButton#statFailedBtn[zero="true"]:hover {
    background:#283546; border-color:#475569; color:#E2E8F0;
}

QPushButton#rtQuickSelectBtn {
    background:#242E3C; color:#CBD5E1; border:1px solid #38475B;
    border-radius:8px; padding:4px 10px; min-height:26px; font-size:12px; font-weight:750;
}
QPushButton#rtQuickSelectBtn:hover { background:#1E3658; color:#93C5FD; border-color:#3B82F6; }
QPushButton#rtQuickSelectBtn[accent="amber"] {
    background:#362915; color:#FCD34D; border:1px solid #78531A;
}
QPushButton#rtQuickSelectBtn[accent="amber"]:hover {
    background:#473518; color:#FDE68A; border-color:#D97706;
}
QPushButton#rtQuickSelectBtn[accent="red"] {
    background:#3A1D24; color:#FCA5A5; border:1px solid #7F2936;
}
QPushButton#rtQuickSelectBtn[accent="red"]:hover {
    background:#4C232D; color:#FECACA; border-color:#EF4444;
}
QPushButton#rtQuickSelectBtn:disabled {
    background:#1C2430; color:#64748B; border:1px solid #2A3544;
}

QPushButton#rtHostMiniBtn {
    background:#242E3C; color:#CBD5E1; border:1px solid #38475B;
    border-radius:7px; padding:0px 8px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#rtHostMiniBtn[iconOnly="true"] {
    padding:0px; min-width:26px; max-width:26px; min-height:22px; max-height:22px;
    font-size:12px; font-weight:800;
}
QPushButton#rtHostMiniBtn:hover {
    background:#1E3658; color:#93C5FD; border-color:#3B82F6;
}
QPushButton#rtHostMiniBtn[active="true"] {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6; font-weight:800;
}
QPushButton#rtHostMiniBtn[kind="retry"] {
    background:#1B3150; color:#93C5FD; border:1px solid #2E5284;
}
QPushButton#rtHostMiniBtn[kind="retry"]:hover {
    background:#23406A; color:#BFDBFE; border-color:#60A5FA;
}
QPushButton#rtHostMiniBtn[kind="import"] {
    background:#163327; color:#6EE7B7; border:1px solid #23533D;
}
QPushButton#rtHostMiniBtn[kind="import"]:hover {
    background:#1A4232; color:#A7F3D0; border-color:#34D399;
}
QPushButton#rtHostMiniBtn[kind="warn"] {
    background:#382B16; color:#FCD34D; border:1px solid #6E4F1D;
}
QPushButton#rtHostMiniBtn[kind="warn"]:hover {
    background:#4A381B; color:#FDE68A; border-color:#F59E0B;
}
QPushButton#rtHostMiniBtn[kind="danger"] {
    background:#3B1E25; color:#FCA5A5; border:1px solid #752A37;
}
QPushButton#rtHostMiniBtn[kind="danger"]:hover {
    background:#4E242E; color:#FECACA; border-color:#F87171;
}
QPushButton#rtHostMiniBtn:disabled {
    background:#1D2532; color:#64748B; border:1px solid #2B3646;
}

QFrame#rtSegRow {
    background:#161E29; border:none; border-bottom:1px solid #212C3B;
}
QFrame#rtSegRow:hover { background:#1D2837; }
QFrame#rtSegRow[tone="stalled"] { background:#231F17; }
QFrame#rtSegRow[tone="failed"], QFrame#rtSegRow[tone="prompt"], QFrame#rtSegRow[tone="upload"] { background:#23191E; }
QFrame#rtSegRow[checked="true"] { background:#1B2E4B; }

QLabel#rtStatusBadge {
    background:#1B3150; color:#93C5FD; border:1px solid #2E5082;
    border-radius:6px; padding:2px 8px; font-size:11px; font-weight:800;
}
QLabel#rtStatusBadge[tone="stalled"] {
    background:#3B2C16; color:#FCD34D; border:1px solid #78531A;
}
QLabel#rtStatusBadge[tone="failed"] {
    background:#3D1D23; color:#FCA5A5; border:1px solid #8A2A35;
}
QLabel#rtStatusBadge[tone="prompt"] {
    background:#381D3D; color:#F0ABFC; border:1px solid #702A7A;
}
QLabel#rtStatusBadge[tone="upload"] {
    background:#3B2316; color:#FDBA74; border:1px solid #7C411E;
}
QLabel#rtStatusBadge[tone="queued"] {
    background:#15333B; color:#67E8F9; border:1px solid #235968;
}
QLabel#rtStatusBadge[tone="running"] {
    background:#1B3150; color:#93C5FD; border:1px solid #2E5082;
}

QComboBox#rtChannelCombo {
    background:#212B38; color:#E2E8F0; border:1px solid #354356;
    border-radius:6px; padding:1px 6px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QComboBox#rtChannelCombo:hover { border-color:#3B82F6; background:#273446; }

QPushButton#rtDangerBtn {
    background:#3B1E25; color:#FCA5A5; border:1px solid #752A37;
    border-radius:9px; padding:6px 14px; font-weight:750;
}
QPushButton#rtDangerBtn:hover { background:#4E242E; border-color:#EF4444; color:#FECACA; }
QPushButton#rtDangerBtn:disabled { background:#1D2532; color:#64748B; border-color:#2B3646; }

/* ---- 自动剪辑中文错误提示 + 「查看详情」迷你按钮与诊断弹窗 (Dark) ---- */
QLabel#cardMeta[isError="true"],
QLabel#tcGuideHint[isError="true"],
QLabel#muted[isError="true"] {
    color:#FCA5A5; font-weight:700;
}
QPushButton#dvErrDetailBtn {
    background:#3B1E25; color:#FCA5A5; border:1px solid #7F2936;
    border-radius:11px; padding:0px 9px; min-height:22px; max-height:22px;
    font-size:11px; font-weight:750;
}
QPushButton#dvErrDetailBtn:hover {
    background:#4E242E; color:#FECACA; border-color:#EF4444;
}
QPushButton#dvErrDetailBtn:pressed {
    background:#5F2936; color:#FFFFFF;
}

QScrollArea#dvErrScroll, QWidget#dvErrScrollBody {
    background:transparent; border:none;
}
QFrame#dvErrHeroCard {
    background:#2B1920; border:1px solid #6E2532; border-radius:12px;
}
QLabel#dvErrStageBadge {
    background:#3F1E28; color:#FCA5A5; border:1px solid #8A2E3D;
    border-radius:8px; padding:2px 9px; font-size:11px; font-weight:800;
}
QLabel#dvErrTitle {
    color:#FECACA; font-size:15px; font-weight:800;
}
QFrame#dvErrLocCard {
    background:#1B2430; border:1px solid #3B2832; border-radius:8px;
}
QLabel#dvErrLocKey {
    color:#94A3B8; font-size:12px; font-weight:700;
}
QLabel#dvErrLocVal {
    color:#F1F5F9; font-size:12px; font-weight:700;
}
QFrame#dvErrDialogCard {
    background:#1C2532; border:1px solid #2E3B4E; border-radius:12px;
}
QFrame#dvErrSolutionsCard {
    background:#182436; border:1px solid #2D4F7C; border-radius:12px;
}
QLabel#dvErrSectionTitle {
    color:#F1F5F9; font-size:13px; font-weight:800;
}
QLabel#dvErrBodyText {
    color:#CBD5E1; font-size:13px; line-height:1.5;
}
QLabel#dvErrStepBadge {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6;
    border-radius:11px; font-size:11px; font-weight:800;
}
QLabel#dvErrStepText {
    color:#E2E8F0; font-size:13px; font-weight:600;
}
QPushButton#dvErrRawToggleBtn {
    background:transparent; color:#94A3B8; border:none; padding:2px 4px;
    font-size:12px; font-weight:600; text-align:left;
}
QPushButton#dvErrRawToggleBtn:hover { color:#93C5FD; }
QPlainTextEdit#dvErrRawBox {
    background:#141B24; color:#94A3B8; border:1px solid #2A3647;
    border-radius:8px; padding:6px 8px; font-size:11px;
    font-family:"SF Mono","Menlo","Consolas",monospace;
}

/* ---- 通用轻量确认弹窗样式 (Dark) ---- */
QDialog#modernConfirmDialog {
    background:#151B23;
}
QFrame#modernConfirmCard {
    background:#1C2532; border:1px solid #2E3B4E; border-radius:14px;
}
QFrame#modernConfirmCard[tone="danger"] {
    background:#281920; border:1px solid #6E2532;
}
QLabel#modernConfirmIcon {
    background:#1E3A5F; color:#93C5FD; border:1px solid #3B82F6;
    border-radius:10px; font-size:17px; font-weight:800;
}
QLabel#modernConfirmIcon[tone="danger"] {
    background:#3B1E25; color:#FCA5A5; border:1px solid #7F2936;
}
QLabel#modernConfirmHeadline {
    color:#F1F5F9; font-size:15px; font-weight:800; background:transparent;
}
QLabel#modernConfirmSub {
    color:#94A3B8; font-size:12.5px; font-weight:600; background:transparent;
}
QFrame#modernConfirmBullets {
    background:#161E29; border:1px solid #283546; border-radius:10px;
}
QLabel#modernConfirmBulletItem {
    color:#CBD5E1; font-size:12.5px; font-weight:650; background:transparent;
}
QPushButton#modernConfirmCancelBtn {
    background:#242E3C; color:#CBD5E1; border:1px solid #38475B;
    border-radius:9px; padding:0 16px; font-size:13px; font-weight:700;
}
QPushButton#modernConfirmCancelBtn:hover {
    background:#2E3B4E; color:#FFFFFF; border-color:#4B6EA8;
}
QPushButton#modernConfirmExtraBtn {
    background:#1B3150; color:#93C5FD; border:1px solid #2E5284;
    border-radius:9px; padding:0 16px; font-size:13px; font-weight:750;
}
QPushButton#modernConfirmExtraBtn:hover {
    background:#23406A; border-color:#60A5FA;
}
QPushButton#modernConfirmOkBtn {
    background:#3B82F6; color:#FFFFFF; border:none;
    border-radius:9px; padding:0 18px; font-size:13px; font-weight:800;
}
QPushButton#modernConfirmOkBtn:hover {
    background:#2563EB;
}
QPushButton#modernConfirmOkBtn[tone="danger"] {
    background:#DC2626; color:#FFFFFF;
}
QPushButton#modernConfirmOkBtn[tone="danger"]:hover {
    background:#B91C1C;
}
'''
