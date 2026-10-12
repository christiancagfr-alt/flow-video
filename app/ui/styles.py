
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
QScrollArea#workflowPageScroll, QScrollArea#pageScroll { border:none; background:transparent; }
QScrollArea#workflowPageScroll QWidget#qt_scrollarea_viewport, QScrollArea#pageScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#workflowPageContent, QWidget#pageScrollContent { background:transparent; }
'''
DARK += r'''
QScrollArea#workflowPageScroll, QScrollArea#pageScroll { border:none; background:transparent; }
QScrollArea#workflowPageScroll QWidget#qt_scrollarea_viewport, QScrollArea#pageScroll QWidget#qt_scrollarea_viewport { background:transparent; }
QWidget#workflowPageContent, QWidget#pageScrollContent { background:transparent; }
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
'''
DARK += r'''
QPushButton#generationModeFrame, QPushButton#generationModeMaterial {
    min-height:30px; border-radius:7px; padding:4px 8px; font-weight:700;
    background:#202833; color:#9AA7BA; border:1px solid #465468;
}
QPushButton#generationModeFrame:hover, QPushButton#generationModeMaterial:hover { background:#283442; }
QPushButton#generationModeFrame:checked { background:#243F6E; color:#9DBAFF; border-color:#4B82F1; }
QPushButton#generationModeMaterial:checked { background:#183B2F; color:#70E0A6; border-color:#2D654E; }
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
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{background:#2867D5;color:white;}}
    QLabel#muted {{color:{_muted};}}
    QAbstractSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {{color:{_muted};background:{_bg};}}
    """
    if _dark: DARK += _extra
    else: LIGHT += _extra

def apply_control_palette(app, dark):
    from app.ui.control_guard import install_control_guard
    install_control_guard(app)
    from PySide6.QtGui import QPalette, QColor
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
