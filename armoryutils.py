#!/usr/bin/env python

import cgi
import collections
import copy
import csv
import datetime
import itertools
import json
import optparse
import random
import re
import sqlite3
import sys
import time
import urllib
import urllib2
import xml.etree.ElementTree



def usage(sys_argv):
    op = optparse.OptionParser()
    usage_setup(op)
    return op.parse_args(sys_argv)

def usage_setup(op, **kwargs):
    if kwargs.get('armorydb', True):
        op.add_option("--armorydb"
                , help="Desired sqlite database output file name."
                , metavar="DB"
                , dest="armorydb_path"
                , action="store"
                , type="str"
                , default="armory.db"
            )

    if kwargs.get('realm', True):
        op.add_option("--realm"
                , help="Realm to use for armory data queries."
                , metavar="REALM"
                , dest="realm_str"
                , action="store"
                , type="str"
                , default="Proudmoore"
            )
    
    if kwargs.get('region', True):
        op.add_option("--region"
                , help="Region to use for armory data queries (www, eu, kr, cn, tw)."
                , metavar="REGION"
                , dest="region_str"
                , action="store"
                , type="str"
                , default="www"
            )



armoryField_list = ['name', 'class', 'level', 'guildName', 'faction', 'gender', 'race']

def sqlite_scrapeCharacters(db_path, name_list, realm_str, region_str, maxAge_td=datetime.timedelta(14), force=False):
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    
    try:
        row_list = conn.execute('''select name from toon where updatedAt > ?''', (datetime.datetime.now() - maxAge_td,))
        print "row_list", row_list
    except Exception, e:
        print "Dropping...", e
        row_list = []
        conn.execute('''drop table if exists toon''')
        conn.execute('''create table toon (id integer primary key, updatedAt timestamp, %s, specName1, specPoints1, specName2, specPoints2)''' % ', '.join(armoryField_list))
        
    name_set = set()
    for row in row_list:
        name_set.add(row['name'])
    
    print "name_list, name_set:", name_list, name_set
    for name_str in name_list or []:
        if name_str not in name_set:
            armory_dict = dict_scrapeCharacter(name_str, realm_str, region_str)
            
            #print armory_dict
            
            if armory_dict:
                colval_list = list(armory_dict.items())
                
                col_list = [x[0] for x in colval_list]
                val_list = [x[1] for x in colval_list]
                
                conn.execute('''insert into toon (updatedAt, %s) values (?, %s) ''' % (', '.join(col_list), ', '.join(['?' for x in col_list])), tuple([datetime.datetime.now()] + val_list))
    conn.commit()
    
    return dict([(x['name'], x) for x in conn.execute('''select * from toon''').fetchall()])
    
    
    
def dict_scrapeCharacter(name_str, realm_str, region_str):
    armory_dict = {}
    try:
        opener = urllib2.build_opener()
        opener.addheaders = [('User-agent', 'Mozilla/5.0 (Macintosh; U; Intel Mac OS X; en-US; rv:1.8.1.6) Gecko/20070725 Firefox/2.0.0.6')]
        
        time.sleep(5)
        xml_str = opener.open("http://%s.wowarmory.com/character-sheet.xml?r=%s&n=%s" % (region_str, realm_str, name_str)).read()
        armory_xml = xml.etree.ElementTree.XML(xml_str)
        
        #print "http://%s.wowarmory.com/character-sheet.xml?r=%s&n=%s" % (region_str, realm_str, name_str)
        #print armory_xml, list(armory_xml.getchildren())
        
        character_elem = armory_xml.find('characterInfo').find('character')
        
        #print character_elem, character_elem.attrib
        
        for col_str in armoryField_list:
            try:
                armory_dict[col_str] = character_elem.get(col_str)
            except:
                pass
            
        for talent_elem in armory_xml.find('characterInfo').find('characterTab').find('talentSpecs').findall('talentSpec'):
            index_str = talent_elem.get('group')
            
            armory_dict['specName' + index_str] = talent_elem.get('prim')
            armory_dict['specPoints' + index_str] = '/'.join([talent_elem.get('tree' + x) for x in ('One', 'Two', 'Three')])

        return armory_dict
    except Exception, e:
        print e
        #raise
        return {}



def classColors():
    color_dict = {
            'Death Knight': ((196, 30, 59), (0.77, 0.12, 0.23), '#C41F3B'),
            'Druid': ((255, 125, 10), (1.00, 0.49, 0.04), '#FF7D0A'),
            'Hunter': ((171, 212, 115), (0.67, 0.83, 0.45), '#ABD473'),
            'Mage': ((105, 204, 240), (0.41, 0.80, 0.94), '#69CCF0'),
            'Paladin': ((245, 140, 186), (0.96, 0.55, 0.73), '#F58CBA'),
            'Priest': ((255, 255, 255), (1.00, 1.00, 1.00), '#FFFFFF'),
            'Rogue': ((255, 245, 105), (1.00, 0.96, 0.41), '#FFF569'),
            'Shaman': ((36, 89, 255), (0.14, 0.35, 1.00), '#2459FF'),
            'Warlock': ((148, 130, 201), (0.58, 0.51, 0.79), '#9482C9'),
            'Warrior': ((199, 156, 110), (0.78, 0.61, 0.43), '#C79C6E'),
        }

    return color_dict



def main(sys_argv):
    options, arguments = usage(sys_argv)
    
    sqlite_scrapeCharacters(options.armorydb_path, arguments, options.realm_str, options.region_str)



if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)

# eof