#!/usr/bin/env python3

import bpaTools
import aixmReader
from shapely.geometry import LineString, Point


class Aixm2openair:
    
    def __init__(self, oCtrl):
        bpaTools.initEvent(__file__, oCtrl.oLog)
        self.oCtrl = oCtrl
        self.oAirspacesCatalog = None
        self.geoBorders = None                    #Geographic borders dictionary
        self.geoAirspaces = None                  #Geographic airspaces dictionary
        return        

    def parseGeographicBorders(self):
        sTitle = "Geographic borders"
        sXmlTag = "Gbr"
        
        sMsg = "Parsing {0} to OpenAir - {1}".format(sXmlTag, sTitle)
        self.oCtrl.oLog.info(sMsg)
        
        if self.geoBorders == None:
            self.geoBorders = dict()
            oList = self.oCtrl.oAixm.doc.find_all(sXmlTag)
            barre = bpaTools.ProgressBar(len(oList), 20, title=sMsg, isSilent=self.oCtrl.oLog.isSilent)
            idx = 0
            openair = []
            for gbr in oList:
                idx+=1
                j,l = self.gbr2openair(gbr)
                openair.append(j)
                self.geoBorders[gbr.GbrUid["mid"]] = LineString(l)
                barre.update(idx)
        barre.reset()
        self.oCtrl.oAixmTools.writeOpenairFile("borders", openair)
        return

    def gbr2openair(self, gbr):
        openair = []
        l = []
        sName = list(self.oCtrl.oAixmTools.getField(gbr.GbrUid, "txtName").values())[0]
        openair.append("AC G")
        openair.append("AN Geographic border - {0}".format(sName))
        openair.append("AH SFC")        #or "AH 500 FT AMSL"
        openair.append("AL SFC")
        # geometry
        for gbv in gbr.find_all("Gbv"):
            if gbv.codeType.string not in ("GRC", "END"):
                self.oCtrl.oLog.critical("codetype non reconnu\n{0}".format(gbv), outConsole=True)
            lon, lat = self.oCtrl.oAixmTools.geo2coordinates(gbv)
            l.append((lon, lat))
            lat1, lon1 = bpaTools.GeoCoordinates.geoDd2dms(lat,"lat", lon,"lon", ":"," ")
            openair.append("DP {0} {1}".format(lat1, lon1))
        return openair, l

    def findOpenairObjectAirspacesBorders(self, sAseUid):
        for o in self.geoAirspaces:
            if o["properties"]["UId"]==sAseUid:
                return o["geometry"]
        return None
    
    def parseAirspacesBorders(self, airspacesCatalog):
        self.oAirspacesCatalog = airspacesCatalog
        
        #Controle de prerequis
        if self.geoBorders == None:
            self.parseGeographicBorders()
            
        sTitle = "Airspaces Borders"
        sXmlTag = "Abd"
        
        if not self.oCtrl.oAixm.doc.find(sXmlTag):
            sMsg = "Missing tags {0} - {1}".format(sXmlTag, sTitle)
            self.oCtrl.oLog.warning(sMsg, outConsole=True)
            return
        
        sMsg = "Parsing {0} to OpenAir - {1}".format(sXmlTag, sTitle)
        self.oCtrl.oLog.info(sMsg)
        
        barre = bpaTools.ProgressBar(len(self.oAirspacesCatalog.oAirspaces), 20, title=sMsg, isSilent=self.oCtrl.oLog.isSilent)
        idx = 0
        self.geoAirspaces = []                #Réinitialisation avant traitement global
        for k,oZone in self.oAirspacesCatalog.oAirspaces.items():
            idx+=1
            if not oZone["groupZone"]:          #Ne pas traiter les zones de type 'Regroupement'
                sAseUid = oZone["UId"]
                oBorder = self.oAirspacesCatalog.findAixmObjectAirspacesBorders(sAseUid)
                if oBorder:
                    self.parseAirspaceBorder(oZone, oBorder)
                else:
                    sAseUidBase = self.oAirspacesCatalog.findZoneUIdBase(sAseUid)         #Identifier la zone de base (de référence)
                    if sAseUidBase==None:
                        self.oCtrl.oLog.warning("Missing Airspaces Borders AseUid={0}".format(sAseUid), outConsole=False)
                    else:
                        geom = self.findOpenairObjectAirspacesBorders(sAseUidBase)  #Recherche si la zone de base a déjà été pasrsé
                        if geom:
                            self.geoAirspaces.append({"type":"Feature", "properties":oZone, "geometry":geom})
                        else:
                            oBorder = self.oAirspacesCatalog.findAixmObjectAirspacesBorders(sAseUidBase)
                            if oBorder==None:
                                self.oCtrl.oLog.warning("Missing Airspaces Borders AseUid={0} AseUidBase={1}".format(sAseUid, sAseUidBase), outConsole=False)
                            else:
                                self.parseAirspaceBorder(oZone, oBorder)
            barre.update(idx)
            
        barre.reset()
        return

    def parseAirspaceBorder(self, oZone, oBorder):
        g = []              #geometry
        points4map = []
        
        if oBorder.Circle:
            lon_c, lat_c = self.oCtrl.oAixmTools.geo2coordinates(oBorder.Circle,
                                           latitude=oBorder.Circle.geoLatCen.string,
                                           longitude=oBorder.Circle.geoLongCen.string)
            
            radius = float(oBorder.Circle.valRadius.string)
            if oBorder.uomRadius.string == "NM":
                radius = radius * aixmReader.CONST.nm
            if oBorder.uomRadius.string == "KM":
                radius = radius * 1000
            
            Pcenter = Point(lon_c, lat_c)
            if self.oCtrl.MakePoints4map:
                points4map.append(self.oCtrl.oAixmTools.make_point(Pcenter, "Circle Center of {0}".format(oZone["nameV"])))
            g = self.oCtrl.oAixmTools.make_arc(Pcenter, radius)
            geom = {"type":"Polygon", "coordinates":[g]}
        else:
            avx_list = oBorder.find_all("Avx")
            for avx_cur in range(0,len(avx_list)):
                avx = avx_list[avx_cur]
                
                codeType = avx.codeType.string
                
                # 'Great Circle' or 'Rhumb Line' segment
                if codeType in ["GRC", "RHL"]:
                    p = self.oCtrl.oAixmTools.geo2coordinates(avx)
                    if self.oCtrl.MakePoints4map:
                        pt = Point(p[0], p[1])
                        points4map.append(self.oCtrl.oAixmTools.make_point(pt, "Point {0} of {1}; type={2}".format(avx_cur, oZone["nameV"], codeType)))
                    g.append(p)
                    
                # 'Counter Clockwise Arc' or 'Clockwise Arc'
                #Nota: 'ABE' = 'Arc By Edge' ne semble pas utilisé dans les fichiers SIA-France et Eurocontrol-Europe
                elif codeType in ["CCA", "CWA"]:
                    start = self.oCtrl.oAixmTools.geo2coordinates(avx, recurse=False)                    
                    if avx_cur+1 == len(avx_list):
                        stop = g[0]
                    else:
                        stop = self.oCtrl.oAixmTools.geo2coordinates(avx_list[avx_cur+1], recurse=False)
                    
                    center = self.oCtrl.oAixmTools.geo2coordinates(avx,
                                             latitude=avx.geoLatArc.string,
                                             longitude=avx.geoLongArc.string)
                    
                    #New source
                    Pcenter = Point(center[0], center[1])
                    Pstart = Point(start[0], start[1])
                    Pstop = Point(stop[0], stop[1])
                    
                    if self.oCtrl.MakePoints4map:
                        points4map.append(self.oCtrl.oAixmTools.make_point(Pstart, "Arc Start {0} of {1}".format(avx_cur, oZone["nameV"])))
                        points4map.append(self.oCtrl.oAixmTools.make_point(Pcenter, "Arc Center {0} of {1}".format(avx_cur, oZone["nameV"])))
                        points4map.append(self.oCtrl.oAixmTools.make_point(Pstop, "Arc Stop {0} of {1}".format(avx_cur, oZone["nameV"])))
                    
                    #Alignement pas toujours idéal sur les extremités d'arcs
                    radius = float(avx.valRadiusArc.string)
                    if avx.uomRadiusArc.string == "NM":
                        radius = radius * aixmReader.CONST.nm
                    if avx.uomRadiusArc.string == "KM":
                        radius = radius * 1000
                        
                    #Test non-concluant - Tentative d'amélioration des arc par recalcul systématique du rayon sur la base des coordonnées des points
                    #arc = self.oCtrl.oAixmTools.make_arc2(Pcenter, Pstart, Pstop, 0.0, (codeType=="CWA"))
                    arc = self.oCtrl.oAixmTools.make_arc2(Pcenter, Pstart, Pstop, radius, (codeType=="CWA"))
                    for o in arc:
                        g.append(o)

                # 'Sequence of geographical (political) border vertexes'
                elif codeType == "FNT":
                    # geographic borders
                    start = self.oCtrl.oAixmTools.geo2coordinates(avx)
                    if avx_cur+1 == len(avx_list):
                        stop = g[0]
                    else:
                        stop = self.oCtrl.oAixmTools.geo2coordinates(avx_list[avx_cur+1])
                        
                    if avx.GbrUid["mid"] in self.geoBorders:
                        fnt = self.geoBorders[avx.GbrUid["mid"]]
                        start_d = fnt.project(Point(start[0], start[1]), normalized=True)
                        stop_d = fnt.project(Point(stop[0], stop[1]), normalized=True)
                        geom = self.oCtrl.oAixmTools.substring(fnt, start_d, stop_d, normalized=True)
                        for c in geom.coords:
                            lon, lat = c
                            g.append([lon, lat])
                    else:
                        self.oCtrl.oLog.warning("Missing geoBorder GbrUid='{0}' Name={1}".format(avx.GbrUid["mid"], avx.GbrUid.txtName.string), outConsole=False)
                        g.append(start)
                else:
                    g.append(self.oCtrl.oAixmTools.geo2coordinates(avx))
    
            if len(g) == 0:
                self.oCtrl.oLog.error("Geometry vide\n{0}".format(oBorder.prettify()), outConsole=True)
                geom = None
            elif len(g) == 1:
                geom = {"type":"Point", "coordinates":g[0]}
            elif len(g) == 2:
                geom = {"type":"LineString", "coordinates":g}
            else:
                #Contrôle de fermeture du Polygone
                if g[0] != g[-1]:
                    g.append(g[0])
                geom = {"type":"Polygon", "coordinates":[g]}
        
        #Ajout spécifique des points complémentaires pour map des cartographies
        for g0 in points4map:
            for g1 in g0:
                self.geoAirspaces.append(g1)
        self.geoAirspaces.append({"type":"Feature", "properties":oZone, "geometry":geom})
        return

