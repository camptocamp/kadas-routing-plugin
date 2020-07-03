import os
from PyQt5 import uic
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMessageBox

from kadas.kadasgui import (
    KadasBottomBar, KadasPinItem, KadasItemPos, KadasMapCanvasItemManager, KadasLayerSelectionWidget)
from kadasrouting.gui.locationinputwidget import LocationInputWidget, WrongLocationException
from kadasrouting import vehicles
from kadasrouting.utilities import iconPath

from qgis.utils import iface
from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsLineSymbol,
    QgsSingleSymbolRenderer,
    QgsCoordinateReferenceSystem
    )

from qgisvalhalla.client import ValhallaClient

WIDGET, BASE = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'shortestpathbottombar.ui'))

class ShortestPathBottomBar(KadasBottomBar, WIDGET):

    def __init__(self, canvas, action):
        KadasBottomBar.__init__(self, canvas, "orange")
        self.setupUi(self)
        self.setStyleSheet("QFrame { background-color: orange; }")
        self.action = action
        self.canvas = canvas
        self.waypoints = []
        self.waypointPins = []

        self.btnAddWaypoints.setIcon(QIcon(":/kadas/icons/add"))
        self.btnClose.setIcon(QIcon(":/kadas/icons/close"))
        self.btnAddWaypoints.setToolTip('Add waypoint')
        self.btnClose.setToolTip('Close routing dialog')

        # self.action.toggled.connect(self.actionToggled)
        self.btnClose.clicked.connect(self.action.toggle)

        self.btnCalculate.clicked.connect(self.calculate)

        self.layerSelector = KadasLayerSelectionWidget(canvas, iface.layerTreeView(),
                                                        lambda x: isinstance(x, QgsVectorLayer)
                                                            and x.geometryType() == QgsWkbTypes.LineGeometry,
                                                        self.createLayer);
        self.layerSelector.createLayerIfEmpty("Route")
        self.layout().addWidget(self.layerSelector, 0, 0, 1, 2)

        self.originSearchBox = LocationInputWidget(canvas)
        self.originSearchBox = LocationInputWidget(canvas, locationSymbolPath=iconPath('pin_origin.svg'))
        self.layout().addWidget(self.originSearchBox, 2, 1)

        self.destinationSearchBox = LocationInputWidget(canvas, locationSymbolPath=iconPath('pin_destination.svg'))
        self.layout().addWidget(self.destinationSearchBox, 3, 1)

        self.waypointsSearchBox = LocationInputWidget(canvas)
        self.layout().addWidget(self.waypointsSearchBox, 4, 1)

        self.comboBoxVehicles.addItems(vehicles.vehicles)

        self.pushButtonClear.clicked.connect(self.clear)
        self.pushButtonReverse.clicked.connect(self.reverse)
        self.btnAddWaypoints.clicked.connect(self.addWaypoints)

        # Add pins if there is already chosen origin, destination, or waypoint
        # self.addPins()

    def createLayer(self, name):
        layer = QgsVectorLayer("LineString", name, "memory")
        props = {'line_color': '255,0,0,255', 'line_style': 'solid',
                'line_width': '2', 'line_width_unit': 'MM'}
        symbol = QgsLineSymbol.createSimple(props)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
        return layer

    def calculate(self):
        try:
            points = [self.originSearchBox.valueAsPoint()]
            points.extend(self.waypoints)
            points.append(self.destinationSearchBox.valueAsPoint())
        except WrongLocationException as e:
            iface.messageBar().pushMessage("Error", "Invalid location %s" % str(e), level=Qgis.Warning)
            return

        shortest = self.radioButtonShortest.isChecked()
        '''
        vehicle = self.comboBoxVehicle.currentIndex()
        costingOptions = vehicles.options[vehicle]
        '''
        costingOptions = {}
        valhalla = ValhallaClient()
        try:
            route = valhalla.route(points, costingOptions, shortest)
            self.processRouteResult(route)
        except:
            #TODO more fine-grained error control
            iface.messageBar().pushMessage("Error", "Could not compute route", level=Qgis.Warning)

    def processRouteResult(self, route):
        layer = self.layerSelector.getSelectedLayer()
        provider = layer.dataProvider()
        provider.truncate()
        provider.deleteAttributes(provider.attributeIndexes())
        provider.addFeatures(route.getFeatures())
        layer.updateFields()
        layer.updateExtents()
        layer.triggerRepaint()

    def clear(self):
        self.originSearchBox.clearSearchBox()
        self.destinationSearchBox.clearSearchBox()
        self.waypointsSearchBox.clearSearchBox()
        self.waypoints = []
        self.lineEditWaypoints.clear()
        for waypointPin in self.waypointPins:
            KadasMapCanvasItemManager.removeItem(waypointPin)
        self.waypointPins = []
        KadasMapCanvasItemManager.removeItem(self.originSearchBox.pin)
        KadasMapCanvasItemManager.removeItem(self.destinationSearchBox.pin)

    def addWaypoints(self):
        """Add way point to the list of way points"""
        if self.waypointsSearchBox.text() == '':
            return
        waypoint = self.waypointsSearchBox.valueAsPoint()
        self.waypoints.append(waypoint)
        if self.lineEditWaypoints.text() == '':
            self.lineEditWaypoints.setText(self.waypointsSearchBox.text())
        else:
            self.lineEditWaypoints.setText(self.lineEditWaypoints.text() + ';' + self.waypointsSearchBox.text())
        self.waypointsSearchBox.clearSearchBox()
        # Remove way point pin from the location input widget
        self.waypointsSearchBox.removePin()
        # Create/add new waypoint pin for the waypoint
        self.addWaypointPin(waypoint)

    def reverse(self):
        """Reverse route"""
        originLocation = self.originSearchBox.text()
        self.originSearchBox.setText(self.destinationSearchBox.text())
        self.destinationSearchBox.setText(originLocation)
        self.waypoints.reverse()
        self.waypointPins.reverse()
        waypointsCoordinates = []
        for waypoint in self.waypoints:
            waypointsCoordinates.append('%f, %f' % (waypoint.x(), waypoint.y()))
        self.lineEditWaypoints.setText(';'.join(waypointsCoordinates))

    def pushMessage(self, text):
        iface.messageBar().pushMessage("Log", text, level=Qgis.Info)

    def addWaypointPin(self, waypoint):
        """Create a new pin for a waypoint with its symbology"""
                # Create pin with waypoint symbology
        canvasCrs = QgsCoordinateReferenceSystem(4326)
        waypointPin = KadasPinItem(canvasCrs)
        waypointPin.setPosition(KadasItemPos(waypoint.x(), waypoint.y()))
        waypointPin.setup(':/kadas/icons/waypoint', waypointPin.anchorX(), waypointPin.anchorX(), 32, 32)
        self.waypointPins.append(waypointPin)
        KadasMapCanvasItemManager.addItem(waypointPin)

    def clearPins(self):
        """Remove all pins from the map
        Not removing the point stored.
        """
        # remove origin pin
        self.originSearchBox.removePin()
        # remove destination poin
        self.destinationSearchBox.removePin()
        # remove waypoint pins
        for waypointPin in self.waypointPins:
            KadasMapCanvasItemManager.removeItem(waypointPin)

    def addPins(self):
        """Add pins for all stored points."""
        # Add for origin
        try:
            originPoint = self.originSearchBox.valueAsPoint()
            self.pushMessage('Origin point %f, %f' % (originPoint.x(), originPoint.y()))
            self.originSearchBox.addPin(originPoint)
        except Exception as e:
            self.pushMessage('Can not add pin for origin because %s' % str(e))
        # Add for destination
        # try:
        #     destinationPoint = self.destinationSearchBox.valueAsPoint()
        #     self.destinationSearchBox.addPin(destinationPoint)
        # except Exception as e:
        #     self.pushMessage('Can not add pin for desination because %s' % str(e))
        # # Add for waypoints
        # for waypointPin in self.waypointPins:
        #     self.addWaypointPin(waypointPin)

    def actionToggled(self, toggled):
        if toggled:
            self.pushMessage('Toggled: %s. Should add pins' % toggled)
            self.addPins()
        else:
            self.pushMessage('Toggled: %s. Should REMOVE pins' % toggled)
            self.clearPins()