from base64 import b64encode
from datetime import datetime
import os
import traceback

from PyQt4.QtGui import *
from PyQt4.QtCore import *

from electrum_dash import bitcoin
from electrum_dash.i18n import _
from electrum_dash.masternode import MasternodeAnnounce
from electrum_dash.masternode_manager import parse_masternode_conf
from electrum_dash.util import PrintError

from masternode_widgets import *
from masternode_budget_widgets import *
import util

# Background color for enabled masternodes.
ENABLED_MASTERNODE_BG = '#80ff80'

class MasternodesModel(QAbstractTableModel):
    """Model for masternodes."""
    ALIAS = 0
    STATUS = 1
    VIN = 2
    COLLATERAL = 3
    DELEGATE = 4
    ADDR = 5
    PROTOCOL_VERSION = 6
    TOTAL_FIELDS = 7


    def __init__(self, manager, parent=None):
        super(MasternodesModel, self).__init__(parent)
        self.manager = manager
        self.masternodes = self.manager.masternodes

        headers = [
            {Qt.DisplayRole: 'Alias',},
            {Qt.DisplayRole: 'Status',},
            {Qt.DisplayRole: 'Collateral',},
            {Qt.DisplayRole: 'Collateral Key',},
            {Qt.DisplayRole: 'Delegate Key',},
            {Qt.DisplayRole: 'Address',},
            {Qt.DisplayRole: 'Version',},
        ]
        for d in headers:
            d[Qt.EditRole] = d[Qt.DisplayRole]
        self.headers = headers

    def add_masternode(self, masternode, save = True):
        self.beginResetModel()
        self.manager.add_masternode(masternode, save)
        self.endResetModel()

    def remove_masternode(self, alias, save = True):
        self.beginResetModel()
        self.manager.remove_masternode(alias, save)
        self.endResetModel()

    def masternode_for_row(self, row):
        mn = self.masternodes[row]
        return mn

    def import_masternode_conf_lines(self, conf_lines, pw):
        self.beginResetModel()
        num = self.manager.import_masternode_conf_lines(conf_lines, pw)
        self.endResetModel()
        return num

    def columnCount(self, parent=QModelIndex()):
        return self.TOTAL_FIELDS

    def rowCount(self, parent=QModelIndex()):
        return len(self.masternodes)

    def headerData(self, section, orientation, role = Qt.DisplayRole):
        if role not in [Qt.DisplayRole, Qt.EditRole]: return None
        if orientation != Qt.Horizontal: return None

        data = None
        try:
            data = self.headers[section][role]
        except (IndexError, KeyError):
            pass

        return QVariant(data)

    def data(self, index, role = Qt.DisplayRole):
        data = None
        if not index.isValid():
            return QVariant(data)
        if role not in [Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole, Qt.FontRole, Qt.BackgroundRole]:
            return None

        mn = self.masternodes[index.row()]
        i = index.column()

        if i == self.ALIAS:
            data = mn.alias
        elif i == self.STATUS:
            status = self.manager.masternode_statuses.get(mn.get_collateral_str())
            data = masternode_status(status)
            if role == Qt.BackgroundRole:
                data = QBrush(QColor(ENABLED_MASTERNODE_BG)) if data[0] else None
            # Return the long description for data widget mappers.
            elif role == Qt.EditRole:
                data = data[2]
            else:
                data = data[1]
        elif i == self.VIN:
            txid = mn.vin.get('prevout_hash', '')
            out_n = str(mn.vin.get('prevout_n', ''))
            addr = mn.vin.get('address', '')
            value = str(mn.vin.get('value', ''))
            scriptsig = mn.vin.get('scriptSig', '')
            if role == Qt.EditRole:
                data = ':'.join([txid, out_n, addr, value, scriptsig])
            elif role == Qt.FontRole:
                data = util.MONOSPACE_FONT
            else:
                if all(attr for attr in [txid, out_n, addr]):
                    data = '%s:%s' % (txid, out_n)
                else:
                    data = ''
        elif i == self.COLLATERAL:
            data = mn.collateral_key
            if role in [Qt.EditRole, Qt.DisplayRole, Qt.ToolTipRole] and data:
                data = bitcoin.public_key_to_bc_address(data.decode('hex'))
            elif role == Qt.FontRole:
                data = util.MONOSPACE_FONT
        elif i == self.DELEGATE:
            data = mn.delegate_key
            if role in [Qt.EditRole, Qt.DisplayRole, Qt.ToolTipRole] and data:
                data = self.manager.get_delegate_privkey(data)
            elif role == Qt.FontRole:
                data = util.MONOSPACE_FONT
        elif i == self.ADDR:
            data = ''
            if mn.addr.ip:
                data = str(mn.addr)
        elif i == self.PROTOCOL_VERSION:
            data = mn.protocol_version

        return QVariant(data)

    def setData(self, index, value, role = Qt.EditRole):
        if not index.isValid(): return False

        mn = self.masternodes[index.row()]
        i = index.column()

        if i == self.ALIAS:
            mn.alias = str(value.toString())
        elif i == self.STATUS:
            return True
        elif i == self.VIN:
            s = str(value.toString()).split(':')
            mn.vin['prevout_hash'] = s[0]
            mn.vin['prevout_n'] = int(s[1]) if s[1] else 0
            mn.vin['address'] = s[2]
            mn.vin['value'] = int(s[3]) if s[3] else 0
            mn.vin['scriptSig'] = s[4]
        elif i == self.COLLATERAL:
            return True
        elif i == self.DELEGATE:
            privkey = str(value.toString())
            pubkey = ''
            try:
                # Import the key if it isn't already imported.
                self.manager.import_masternode_delegate(privkey)
                pubkey = bitcoin.public_key_from_private_key(privkey)
            except Exception:
                # Don't fail if the key is invalid.
                pass

            mn.delegate_key = pubkey
        elif i == self.ADDR:
            s = str(value.toString()).split(':')
            mn.addr.ip = s[0]
            mn.addr.port = int(s[1])
        elif i == self.PROTOCOL_VERSION:
            version, ok = value.toInt()
            if not ok:
                return False
            mn.protocol_version = version
        else:
            return False

        self.dataChanged.emit(self.index(index.row(), index.column()), self.index(index.row(), index.column()))
        return True

class MasternodesWidget(QWidget):
    """Widget that displays masternodes."""
    def __init__(self, manager, parent=None):
        super(MasternodesWidget, self).__init__(parent)
        self.manager = manager
        self.model = MasternodesModel(self.manager)
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy_model)
        for header in [self.view.horizontalHeader(), self.view.verticalHeader()]:
            header.setHighlightSections(False)

        header = self.view.horizontalHeader()
        header.setResizeMode(MasternodesModel.ALIAS, QHeaderView.ResizeToContents)
        header.setResizeMode(MasternodesModel.VIN, QHeaderView.Stretch)
        header.setResizeMode(MasternodesModel.COLLATERAL, QHeaderView.ResizeToContents)
        header.setResizeMode(MasternodesModel.DELEGATE, QHeaderView.ResizeToContents)
        self.view.verticalHeader().setVisible(False)

        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(self.model.ALIAS, Qt.AscendingOrder)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self.view)
        self.setLayout(vbox)

    def select_masternode(self, alias):
        """Select the row that represents alias."""
        self.view.clearSelection()
        for i in range(self.proxy_model.rowCount()):
            idx = self.proxy_model.index(i, 0)
            mn_alias = str(self.proxy_model.data(idx).toString())
            if mn_alias == alias:
                self.view.selectRow(i)
                break

    def refresh_items(self):
        self.model.dataChanged.emit(QModelIndex(), QModelIndex())

    def add_masternode(self, masternode, save = True):
        self.model.add_masternode(masternode, save=save)

    def remove_masternode(self, alias, save = True):
        self.model.remove_masternode(alias, save=save)

    def masternode_for_row(self, row):
        idx = self.proxy_model.mapToSource(self.proxy_model.index(row, 0))
        return self.model.masternode_for_row(idx.row())

    def import_masternode_conf_lines(self, conf_lines, pw):
        return self.model.import_masternode_conf_lines(conf_lines, pw)

class MasternodeDialog(QDialog, PrintError):
    """GUI for managing masternodes."""

    def __init__(self, manager, parent):
        super(MasternodeDialog, self).__init__(parent)
        self.gui = parent
        self.manager = manager
        self.setWindowTitle(_('Masternode Manager'))

        self.waiting_dialog = None
        self.create_layout()
        # Create a default masternode if none are present.
        if len(self.manager.masternodes) == 0:
            self.masternodes_widget.add_masternode(MasternodeAnnounce(alias='default'), save=False)
        self.masternodes_widget.view.selectRow(0)

    def sizeHint(self):
        return QSize(770, 600)

    def create_layout(self):
        self.masternodes_widget = MasternodesWidget(self.manager)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_view_masternode_tab(), _('View Masternode'))
        self.tabs.addTab(self.create_sign_announce_tab(), _('Activate Masternode'))
        self.tabs.addTab(self.create_masternode_conf_tab(), _('Masternode.conf'))
        # Disabled until API is stable.
#        self.tabs.addTab(self.create_vote_tab(), _('Vote'))

        # Connect to the selection signal so we can update the widget mapper.
        self.masternodes_widget.view.selectionModel().selectionChanged.connect(self.on_view_selection_changed)

        bottom_buttons = util.Buttons(util.CloseButton(self))

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(_('Masternodes:')))
        vbox.addWidget(self.masternodes_widget, stretch=1)
        vbox.addWidget(self.tabs)
        vbox.addLayout(bottom_buttons)
        self.setLayout(vbox)

    def create_view_masternode_tab(self):
        """Create the tab used to view masternodes."""
        collateral_desc = QLabel(_(''.join(['The "Collateral DASH Output" field below will appear blank until ',
                'you activate this masternode.'])))
        collateral_desc.setWordWrap(True)

        self.masternode_editor = editor = MasternodeEditor()
        model = self.masternodes_widget.proxy_model
        self.mapper = mapper = QDataWidgetMapper()

        editor.alias_edit.textChanged.connect(self.on_editor_alias_changed)

        mapper.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)
        mapper.setModel(model)
        mapper.addMapping(editor.alias_edit, MasternodesModel.ALIAS)
        mapper.addMapping(editor.status_edit, MasternodesModel.STATUS)

        editor.vin_edit.setReadOnly(True)
        mapper.addMapping(editor.vin_edit, MasternodesModel.VIN, 'string')

        mapper.addMapping(editor.addr_edit, MasternodesModel.ADDR, 'string')
        mapper.addMapping(editor.delegate_key_edit, MasternodesModel.DELEGATE)
        mapper.addMapping(editor.protocol_version_edit, MasternodesModel.PROTOCOL_VERSION)

        self.save_new_masternode_button = QPushButton('Save As New Masternode')
        self.save_new_masternode_button.clicked.connect(lambda: self.save_current_masternode(as_new=True))

        self.save_masternode_button = QPushButton(_('Save Masternode'))
        self.save_masternode_button.clicked.connect(self.save_current_masternode)

        self.delete_masternode_button = QPushButton(_('Delete Masternode'))
        self.delete_masternode_button.clicked.connect(self.delete_current_masternode)

        vbox = QVBoxLayout()
        vbox.addWidget(collateral_desc)
        vbox.addWidget(editor)
        vbox.addStretch(1)
        vbox.addLayout(util.Buttons(self.delete_masternode_button,
                self.save_new_masternode_button, self.save_masternode_button))
        w = QWidget()
        w.setLayout(vbox)
        return w

    def create_masternode_conf_tab(self):
        """Create the tab used to import masternode.conf files."""

        desc = ' '.join(['You can use this form to import your masternode.conf file.',
            'This file is usually located in the same directory that your wallet file is in.',
            'If you just need to import your masternode\'s private key, use the regular process for importing a key.'])
        desc = QLabel(_(desc))
        desc.setWordWrap(True)

        import_filename_edit = QLineEdit()
        import_filename_edit.setPlaceholderText(_('Enter the path to your masternode.conf'))
        import_select_file = QPushButton(_('Select File...'))
        hbox = QHBoxLayout()
        hbox.addWidget(import_filename_edit, stretch=1)
        hbox.addWidget(import_select_file)
        import_conf_button = QPushButton(_('Import'))
        vbox = QVBoxLayout()
        vbox.addWidget(desc)
        vbox.addLayout(hbox)
        vbox.addLayout(util.Buttons(import_conf_button))
        vbox.addStretch(1)

        def select_import_file():
            text = QFileDialog.getOpenFileName(None, _('Select a file to import'), '', '*.conf')
            if text:
                import_filename_edit.setText(text)
        import_select_file.clicked.connect(select_import_file)

        def do_import_file():
            path = str(import_filename_edit.text())
            self.import_masternode_conf(path)
        import_conf_button.clicked.connect(do_import_file)

        w = QWidget()
        w.setLayout(vbox)
        return w

    def import_masternode_conf(self, filename):
        """Import a masternode.conf file."""
        pw = None
        if self.manager.wallet.use_encryption:
            pw = self.gui.password_dialog(msg=_('Please enter your password to import Masternode information.'))
            if pw is None:
                return

        if not os.path.exists(filename):
            QMessageBox.critical(self, _('Error'), _('File does not exist'))
            return
        with open(filename, 'r') as f:
            lines = f.readlines()

        # Show an error if the conf file is malformed.
        try:
            conf_lines = parse_masternode_conf(lines)
        except Exception as e:
            QMessageBox.critical(self, _('Error'), _(str(e)))
            return

        num = self.masternodes_widget.import_masternode_conf_lines(conf_lines, pw)
        if not num:
            return QMessageBox.warning(self, _('Failed to Import'), _('Could not import any masternode configurations. Please ensure that they are not already imported.'))
        # Grammar is important.
        configurations = 'configuration' if num == 1 else 'configurations'
        adjective = 'this' if num == 1 else 'these'
        noun = 'masternode' if num == 1 else 'masternodes'
        words = {'adjective': adjective, 'configurations': configurations, 'noun': noun, 'num': num,}
        msg = '{num} {noun} {configurations} imported.\n\nPlease wait for transactions involving {adjective} {configurations} to be retrieved before activating {adjective} {noun}.'.format(**words)
        QMessageBox.information(self, _('Success'), _(msg))

    def selected_masternode(self):
        """Get the currently-selected masternode."""
        row = self.mapper.currentIndex()
        mn = self.masternodes_widget.masternode_for_row(row)
        return mn

    def delete_current_masternode(self):
        """Delete the masternode that is being viewed."""
        mn = self.selected_masternode()
        if QMessageBox.question(self, _('Delete'), _('Do you want to remove the masternode configuration for') + ' %s?'%mn.alias,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.masternodes_widget.remove_masternode(mn.alias)
            self.masternodes_widget.view.selectRow(0)

    def save_current_masternode(self, as_new=False):
        """Save the masternode that is being viewed.

        If as_new is True, a new masternode will be created.
        """
        delegate_privkey = str(self.masternode_editor.delegate_key_edit.text())
        try:
            self.manager.import_masternode_delegate(delegate_privkey)
            delegate_pubkey = bitcoin.public_key_from_private_key(delegate_privkey)
        except Exception:
            # Show an error if the private key is invalid and not an empty string.
            if delegate_privkey:
                QMessageBox.warning(self, _('Warning'), _('Ignoring invalid delegate private key.'))
            delegate_pubkey = ''

        alias = str(self.masternode_editor.alias_edit.text())
        # Construct a new masternode.
        if as_new:
            kwargs = self.masternode_editor.get_masternode_args()
            kwargs['delegate_key'] = delegate_pubkey
            del kwargs['vin']
            self.mapper.revert()
            self.masternodes_widget.add_masternode(MasternodeAnnounce(**kwargs))
        else:
            self.mapper.submit()
        self.manager.save()
        self.masternodes_widget.select_masternode(alias)

    def on_view_selection_changed(self, selected, deselected):
        """Update the data widget mapper."""
        try:
            idx = selected.indexes()[0]
            self.mapper.setCurrentIndex(idx.row())
            self.sign_announce_widget.set_mapper_index(idx.row())
        except Exception:
            self.mapper.setCurrentIndex(0)
            self.sign_announce_widget.set_mapper_index(0)

    def on_editor_alias_changed(self, text):
        """Enable or disable the 'Save As New Masternode' button.

        Aliases must be unique and have at least one character.
        """
        text = str(text)
        # Check if the alias already exists.
        enable = len(text) > 0 and self.manager.get_masternode(text) is None
        self.save_new_masternode_button.setEnabled(enable)

    def create_sign_announce_tab(self):
        desc = ' '.join(['You can sign a Masternode Announce message to activate your masternode.',
            'First, scan for valid 1000 DASH outputs below.',
            'Then, click "Activate Masternode" to activate your masternode.',
        ])
        desc = QLabel(_(desc))
        desc.setWordWrap(True)

        self.sign_announce_widget = SignAnnounceWidget(self)

        vbox = QVBoxLayout()
        vbox.addWidget(desc)
        vbox.addWidget(self.sign_announce_widget)
        vbox.addStretch(1)

        w = QWidget()
        w.setLayout(vbox)
        return w

    def sign_announce(self, alias):
        """Sign an announce for alias. This is called by SignAnnounceWidget."""
        pw = None
        if self.manager.wallet.use_encryption:
            pw = self.gui.password_dialog(msg=_('Please enter your password to activate masternode "%s".' % alias))
            if pw is None:
                return

        # Make sure the masternode is populated with everything we can find out about it.
        self.manager.populate_masternode_output(alias)

        self.sign_announce_widget.sign_button.setEnabled(False)

        def sign_thread():
            return self.manager.sign_announce(alias, pw)

        def on_sign_successful(mn):
            self.print_msg('Successfully signed Masternode Announce.')
            self.send_announce(alias)
        # Proceed to broadcasting the announcement, or re-enable the button.
        def on_sign_error(err):
            self.print_error('Error signing MasternodeAnnounce:')
            # Print traceback information to error log.
            self.print_error(''.join(traceback.format_tb(err[2])))
            self.print_error(''.join(traceback.format_exception_only(err[0], err[1])))
            self.sign_announce_widget.sign_button.setEnabled(True)

        self.print_msg('Signing Masternode Announce message...')
        self.manager.sign_announce(alias, pw)
        # util.WaitingDialog(self, _('Signing Masternode Announce...'), sign_thread, on_sign_successful, on_sign_error)


    def send_announce(self, alias):
        """Send an announce for a masternode."""
        def send_thread():
            return self.manager.send_announce(alias)

        def on_send_successful(result):
            errmsg, was_announced = result
            if was_announced:
                self.print_msg('Successfully broadcasted MasternodeAnnounce for "%s"' % alias)
                QMessageBox.information(self, _('Success'), _('Masternode activated successfully.'))
            else:
                self.print_error('Failed to broadcast MasternodeAnnounce: %s' % errmsg)
                QMessageBox.critical(self, _('Error Sending'), _(errmsg))
            self.masternodes_widget.refresh_items()
            self.masternodes_widget.select_masternode(alias)

        def on_send_error(err):
            self.print_error('Error sending Masternode Announce message:')
            # Print traceback information to error log.
            self.print_error(''.join(traceback.format_tb(err[2])))
            self.print_error(''.join(traceback.format_exception_only(err[0], err[1])))

            self.masternodes_widget.refresh_items()
            self.masternodes_widget.select_masternode(alias)

        self.print_msg('Sending Masternode Announce message...')
        self.manager.send_announce(alias)
        # util.WaitingDialog(self, _('Broadcasting masternode...'), send_thread, on_send_successful, on_send_error)

    def create_vote_tab(self):
        self.proposals_widget = ProposalsWidget(self, self.gui.proposals_list.get_model())
        vbox = QVBoxLayout()
        vbox.addWidget(self.proposals_widget)

        w = QWidget()
        w.setLayout(vbox)
        return w

    def cast_vote(self, proposal_name, vote_yes):
        """Vote for a proposal. This is called by ProposalsWidget."""
        vote_choice = 'yes' if vote_yes else 'no'
        mn = self.selected_masternode()
        if not mn.announced:
            return QMessageBox.critical(self, _('Cannot Vote'), _('Masternode has not been activated.'))
        # Check that we can vote before asking for a password.
        try:
            self.manager.check_can_vote(mn.alias, proposal_name)
        except Exception as e:
            return QMessageBox.critical(self, _('Cannot Vote'), _(str(e)))

        self.proposals_widget.editor.vote_button.setEnabled(False)

        def vote_thread():
            return self.manager.vote(mn.alias, proposal_name, vote_choice)

        # Show the result.
        def on_vote_successful(result):
            errmsg, res = result
            if res:
                QMessageBox.information(self, _('Success'), _('Successfully voted'))
            else:
                QMessageBox.critical(self, _('Error Voting'), _(errmsg))
            self.proposals_widget.editor.vote_button.setEnabled(True)

        def on_vote_failed(err):
            self.print_error('Error sending vote:')
            # Print traceback information to error log.
            self.print_error(''.join(traceback.format_tb(err[2])))
            self.print_error(''.join(traceback.format_exception_only(err[0], err[1])))
            self.proposals_widget.editor.vote_button.setEnabled(True)

        util.WaitingDialog(self, _('Voting...'), vote_thread, on_vote_successful, on_vote_failed)
