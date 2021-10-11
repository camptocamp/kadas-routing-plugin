import os
import json
import logging
import datetime

from PyQt5.QtCore import QTimer, pyqtSignal, Qt
from PyQt5.QtGui import QColor, QPen, QBrush
from PyQt5.QtWidgets import QAction

from kadas.kadasgui import KadasPinItem, KadasItemPos, KadasItemLayer, KadasGpxRouteItem

from kadasrouting.utilities import (
    iconPath,
    waitcursor,
    pushWarning,
    decodePolyline6,
    formatdist,
)

from kadasrouting.valhalla.client import ValhallaClient

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    QgsDistanceArea,
    QgsUnitTypes,
)

from kadasrouting.exceptions import ValhallaException

from kadas.kadascore import KadasPluginLayerType, KadasCoordinateFormat

LOG = logging.getLogger(__name__)

class NotInRouteException(Exception):
    pass


class RoutePointMapItem(KadasPinItem):

    hasChanged = pyqtSignal()

    def itemName(self):
        return "Route point"

    def edit(self, context, pos, settings):
        super().edit(context, pos, settings)
        self.hasChanged.emit()


class OptimalRouteLayer(KadasItemLayer):

    LAYER_TYPE = "optimalroute"

    def __init__(self, name):
        KadasItemLayer.__init__(
            self,
            name,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            OptimalRouteLayer.LAYER_TYPE,
        )
        self.geom = None
        self.response = None
        self.points = []
        self.pins = []
        self.profile = None
        self.costingOptions = {}
        self.lineItem = None
        self.valhalla = ValhallaClient.getInstance()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.updateFromPins)
        self.actionAddAsRegularLayer = QAction(
            self.tr("Add to project as regular layer")
        )
        self.actionAddAsRegularLayer.triggered.connect(self.addAsRegularLayer)

    def setResponse(self, response):
        self.response = response

    def clear(self):
        items = self.items()
        for itemId in items.keys():
            self.takeItem(itemId)
        self.pins = []
        self.maneuvers = {}

    def hasRoute(self):
        return self.geom is not None

    def pinHasChanged(self):
        self.timer.start(1000)

    @waitcursor
    def updateFromPins(self):
        try:
            for i, pin in enumerate(self.pins):
                self.points[i] = QgsPointXY(pin.position())
            response = self.valhalla.route(
                self.points, self.profile, self.costingOptions
            )
            self.computeFromResponse(response)
            self.triggerRepaint()
        except Exception as e:
            logging.error(e, exc_info=True)
            # TODO more fine-grained error control
            pushWarning(self.tr("Could not compute route"))
            logging.error("Could not compute route")

    @waitcursor
    def updateFromPolyline(self, polyline, profile, costingOptions):
        try:
            response = self.valhalla.mapmatching(polyline, profile, costingOptions)
            self.computeFromResponse(response)
        except Exception as e:
            LOG.warning(e)
            pushWarning(self.tr("Could not compute route from polyline"))

    @waitcursor
    def updateRoute(
        self, points, profile, avoid_polygons, costingOptions, patrol_polygons=[]
    ):
        try:
            response = self.valhalla.route(
                points, profile, avoid_polygons, costingOptions, patrol_polygons
            )
            self.costingOptions = costingOptions
            self.profile = profile
            self.points = points
            self.computeFromResponse(response)
            self.triggerRepaint()
        except ValhallaException as e:
            pushWarning(str(e))
            LOG.error(e)

    def computeFromResponse(self, response):
        if response is None:
            return
        epsg4326 = QgsCoordinateReferenceSystem("EPSG:4326")
        self.clear()
        self.response = response
        response_mini = response["trip"]
        coordinates = []
        self.duration = 0
        self.distance = 0
        for leg in response_mini["legs"]:
            leg_coordinates = [
                list(reversed(coord)) for coord in decodePolyline6(leg["shape"])
            ]
            coordinates.extend(leg_coordinates)
            qgis_leg_coords = [QgsPointXY(x, y) for x, y in leg_coordinates]
            geom = QgsGeometry.fromPolylineXY(qgis_leg_coords)
            self.maneuvers[geom] = leg["maneuvers"]
            self.duration += leg["summary"]["time"]
            self.distance += round(leg["summary"]["length"], 3)
        qgis_coords = [QgsPointXY(x, y) for x, y in coordinates]
        self.geom = QgsGeometry.fromPolylineXY(qgis_coords)
        self.lineItem = KadasGpxRouteItem()
        self.lineItem.addPartFromGeometry(self.geom.constGet())
        self.lineItem.setName("route")
        self.lineItem.setNumber("1")
        # Format string for duration
        duration_hour = int(self.duration) // 3600
        duration_minute = (int(self.duration) % 3600) // 60
        formatted_hour = (
            str(duration_hour) if duration_hour >= 10 else "0%d" % duration_hour
        )
        formatted_minute = (
            str(duration_minute) if duration_minute >= 10 else "0%d" % duration_minute
        )
        tooltip = self.tr(
            "Distance: {distance} km<br/>Time: {formatted_hour}h{formatted_minute}"
        ).format(
            distance=self.distance,
            formatted_hour=formatted_hour,
            formatted_minute=formatted_minute,
        )
        self.lineItem.setTooltip(tooltip)
        # Line color: 005EFF
        line_color = QColor(0, 94, 255)
        self.lineItem.setOutline(QPen(line_color, 5))
        self.lineItem.setFill(QBrush(line_color, Qt.SolidPattern))

        self.addItem(self.lineItem)
        for i, pt in enumerate(self.points):
            pin = RoutePointMapItem(epsg4326)
            pin.setPosition(KadasItemPos(pt.x(), pt.y()))
            if i == 0:
                pin.setFilePath(iconPath("pin_origin.svg"))
                pin.setName(self.tr("Origin Point"))
            elif i == len(self.points) - 1:
                pin.setFilePath(iconPath("pin_destination.svg"))
                pin.setName(self.tr("Destination Point"))
            else:
                pin.setup(
                    ":/kadas/icons/waypoint", pin.anchorX(), pin.anchorX(), 32, 32
                )
                pin.setName(self.tr("Waypoint {point_index}").format(point_index=i))
            pin.hasChanged.connect(self.pinHasChanged)
            self.pins.append(pin)
            self.addItem(pin)

    def layerTypeKey(self):
        return OptimalRouteLayer.LAYER_TYPE

    def readXml(self, node, context):
        element = node.toElement()
        response = json.loads(element.attribute("response"))
        points = json.loads(element.attribute("points"))
        self.points = [QgsGeometry.fromWkt(wkt).asPoint() for wkt in points]
        self.costingOptions = json.loads(element.attribute("costingOptions"))
        self.profile = element.attribute("profile")
        self.computeFromResponse(response)
        return True

    def writeXml(self, node, doc, context):
        KadasItemLayer.writeXml(self, node, doc, context)
        element = node.toElement()
        # write plugin layer type to project  (essential to be read from project)
        element.setAttribute("type", "plugin")
        element.setAttribute("name", self.layerTypeKey())
        element.setAttribute("response", json.dumps(self.response))
        element.setAttribute("points", json.dumps([pt.asWkt() for pt in self.points]))
        element.setAttribute("profile", self.profile)
        element.setAttribute("costingOptions", json.dumps(self.costingOptions))
        return True

    def addAsRegularLayer(self):
        layer = QgsVectorLayer(
            "LineString?crs=epsg:4326&field=id:integer&field=distance:double&field=duration:double",
            self.name(),
            "memory",
        )
        pr = layer.dataProvider()
        feature = QgsFeature()
        feature.setAttributes([1, self.distance, self.duration])
        feature.setGeometry(self.geom)
        pr.addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)


class OptimalRouteLayerType(KadasPluginLayerType):
    def __init__(self):
        KadasPluginLayerType.__init__(self, OptimalRouteLayer.LAYER_TYPE)

    def createLayer(self):
        return OptimalRouteLayer("")

    def showLayerProperties(self, layer):
        return True

    def addLayerTreeMenuActions(self, menu, layer):
        menu.addAction(layer.actionAddAsRegularLayer)
