import logging

from qgis.core import (
    QgsSettings,
    QgsGpsDetector,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGpsInformation,
    QgsProject
)

from qgis.utils import iface

from PyQt5.QtCore import QEventLoop, pyqtSignal, QObject

from kadasrouting.utilities import waitcursor

LOG = logging.getLogger(__name__)


@waitcursor
def getGpsConnection():
    gpsConnectionList = QgsApplication.gpsConnectionRegistry().connectionList()
    LOG.debug('gpsConnectionList = {}'.format(gpsConnectionList))
    if len(gpsConnectionList) > 0:
        return gpsConnectionList[0]
    else:
        return None
