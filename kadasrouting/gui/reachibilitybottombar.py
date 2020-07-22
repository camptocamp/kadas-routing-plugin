import os
import logging

log = logging.getLogger(__name__)

from PyQt5 import uic
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QDesktopWidget, QLineEdit

from kadas.kadasgui import (
    KadasBottomBar,
    KadasPinItem,
    KadasItemPos,
    KadasMapCanvasItemManager,
    KadasLayerSelectionWidget
    )
from kadasrouting.gui.locationinputwidget import LocationInputWidget, WrongLocationException
from kadasrouting import vehicles
from kadasrouting.utilities import iconPath, pushMessage, pushWarning, showMessageBox

from qgis.utils import iface
from qgis.core import (
    Qgis,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle
    )

from kadasrouting.core.isochroneslayer import IsochronesLayer

WIDGET, BASE = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'reachibilitybottombar.ui'))

class ReachibilityBottomBar(KadasBottomBar, WIDGET):

    def __init__(self, canvas, action):
        KadasBottomBar.__init__(self, canvas, "orange")
        self.setupUi(self)
        self.setStyleSheet("QFrame { background-color: orange; }")
        self.action = action
        self.canvas = canvas

        self.btnClose.setIcon(QIcon(":/kadas/icons/close"))
        self.btnClose.setToolTip('Close reachibility dialog')

        self.action.toggled.connect(self.actionToggled)
        self.btnClose.clicked.connect(self.action.toggle)

        self.btnCalculate.clicked.connect(self.calculate)

        self.originSearchBox = LocationInputWidget(canvas, locationSymbolPath=iconPath('blue_cross.svg'))
        self.layout().addWidget(self.originSearchBox, 3, 1)
        self.layerSelector = KadasLayerSelectionWidget(canvas, iface.layerTreeView(),
                                                        lambda x: isinstance(x, IsochronesLayer),
                                                        self.createLayer)
        #self.layerSelector.createLayerIfEmpty("Isochrones")
        #self.layout().addWidget(self.layerSelector, 0, 0, 1, 2)

        self.textbox = QLineEdit(self)
        self.textbox.resize(80,40)
        self.textbox.setText("NewIsochrones")
        self.layout().addWidget(self.textbox, 0, 0, 1, 2)


        self.comboBoxVehicles.addItems(vehicles.vehicles)

        self.reachibilityMode = {
            'isochrone': self.tr('Isochrone'),
            'isodistance': self.tr('Isodistance'),
        }

        self.comboBoxReachibiliyMode.addItems(self.reachibilityMode.values())
        self.comboBoxReachibiliyMode.currentIndexChanged.connect(self.setIntervalToolTip)
        self.setIntervalToolTip()

        self.lineEditIntervals.textChanged.connect(self.intervalChanges)
        self.intervalChanges()

        # Update center of map according to selected point
        self.originSearchBox.searchBox.textChanged.connect(self.centerMap)

        # Always set to center of map for the first time
        self.setCenterAsSelected()

        # Update the point when the canvas extent changed.
        self.canvas.extentsChanged.connect(self.setCenterAsSelected)

        # Handling HiDPI screen, perhaps we can make a ratio of the screen size
        size = QDesktopWidget().screenGeometry()
        if size.width() >= 3200 or size.height() >= 1800:
            self.setFixedSize(self.size().width(), self.size().height() * 1.5)

    def setCenterAsSelected(self, point=None):
        # Set the current center of the map as the selected point
        map_center = self.canvas.center()
        self.originSearchBox.updatePoint(map_center, None)

    def centerMap(self):
        """Pan map so that the current selected point as the center of the map canvas."""
        # Get point from the widget
        point = self.originSearchBox.valueAsPoint()
        # Convert point to canvas CRS
        inCrs = QgsCoordinateReferenceSystem(4326)
        canvasCrs = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(inCrs, canvasCrs, QgsProject.instance())
        canvasPoint = transform.transform(point)
        # Center the map to the converted point with the same zoom level
        rect = QgsRectangle(canvasPoint, canvasPoint)
        self.canvas.setExtent(rect)
        self.canvas.refresh()

    def createLayer(self, name):
        layer = IsochronesLayer(name)
        return layer

    def calculate(self):
        clear = self.checkBoxRemovePrevious.isChecked()
        #layer = self.layerSelector.getSelectedLayer()
        #self.layerSelector.createLayerIfEmpty(self.textbox.text())
        log.debug('isochrones layer name = {}'.format(self.textbox.text()))
        
        try:
            layer =  QgsProject.instance().mapLayersByName(self.textbox.text())[0] # FIXME: we do not consider if there are several layers with the same name here
            QgsProject.instance().removeMapLayer( layer.id() )
        except IndexError:
            log.debug('this layer was not found: {}'.format(self.textbox.text()))
        layer = self.createLayer(self.textbox.text())
        QgsProject.instance().addMapLayer(layer)
        self.layerSelector.setSelectedLayer(layer)

        if layer is None:
            pushWarning("Please, select a valid destination layer")
            return
        try:
            point = self.originSearchBox.valueAsPoint()
        except WrongLocationException as e:
            pushWarning("Invalid location %s" % str(e))
            return
        try:
            intervals = self.getInterval()
            if len(intervals) == 0:
                raise Exception()
        except Exception as e:
            pushWarning("Invalid intervals")
            return
        try:
            layer.updateRoute(point, intervals, clear)
        except Exception as e:
            logging.error(e, exc_info=True)
            #TODO more fine-grained error control
            pushWarning("Could not compute isochrones")

    def actionToggled(self, toggled):
        if toggled:
            self.setCenterAsSelected()
        else:
            self.originSearchBox.removePin()

    def intervalChanges(self):
        """Slot when the text on the interval line edit changed.

        It set the text color to red, disable the calculate button,
        and update the calculate button tooltip.
        """
        try:
            interval = self.getInterval()
            if len(interval) == 0:
                raise Exception('Interval can not be empty')
            self.lineEditIntervals.setStyleSheet("color: black;")
            self.btnCalculate.setEnabled(True)
            self.btnCalculate.setToolTip('')
        except Exception as e:
            pushMessage(str(e))
            self.lineEditIntervals.setStyleSheet("color: red;")
            self.btnCalculate.setEnabled(False)
            self.btnCalculate.setToolTip('Please make sure the interval is correct.')

    def getInterval(self):
        """Get interval of as a list of integer or float based on the current mode.
        It also make sure that the list is ascending
        """
        intervalText = self.lineEditIntervals.text()
        # remove white space
        intervalText = ''.join(intervalText.split())
        interval = intervalText.split(';')
        if self.comboBoxReachibiliyMode.currentText() == self.reachibilityMode['isochrone']:
            # try to convert to int for isochrone
            interval = [int(x) for x in interval if len(x) > 0]
        else:
            # try to convert to float for isodistance
            interval = [float(x) for x in interval if len(x) > 0]
        # sort it
        return sorted(interval)

    def setIntervalToolTip(self):
        """Set the tool tip for interval line edit based on the current mode."""
        if self.comboBoxReachibiliyMode.currentText() == self.reachibilityMode['isochrone']:
            self.lineEditIntervals.setToolTip(
                'Set interval as interger in minutes, separated by ";" symbol')
        else:
            self.lineEditIntervals.setToolTip(
                'Set interval as float in KM, separated by ";" symbol')
