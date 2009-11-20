#!/usr/bin/env python

#Copyright (c) 2009, Eli Stevens
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#THE SOFTWARE.

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

import basicparse
import armoryutils

#from sqliteutils import conn_execute, DurationManager
from sqliteutils import *


class WipeRun(DataRun):
    def __init__(self):
        DataRun.__init__(self, ['CombatRun', 'WoundRun', 'AuraRun', 'FakeDeathRun'], [])
        
    def impl(self, options):
        sqlite_insureColumns(self.conn, 'event', [('wipe', 'int default 0')])

        for combat in conn_execute(self.conn, '''select * from combat order by start_event_id''').fetchall():
            conn_execute(self.conn, '''update event set wipe = 0 where id >= ? and id <= ?''', (combat['start_event_id'], combat['end_event_id']))
                
            # Note: the limit 3 means we actually get the 3rd-to-last heal.
            lastHeal_wound = conn_execute(self.conn, '''select * from wound where combat_id = ? and direction = ? order by start_event_id desc limit 3''', (combat['id'], 1)).fetchall()
            
            select_str = '''select * from wound where combat_id = ? and end_event_id = ? and dead = ? and destType = ? and destName in (%s) order by start_event_id desc'''
            base_tup = (combat['id'], combat['end_event_id'], 1, 'PC')

            dpsDeath_list = conn_execute(self.conn, select_str % ','.join(['?' for x in combat['dps_list']]), base_tup + tuple(combat['dps_list'])).fetchall()
            tankDeath_list = conn_execute(self.conn, select_str % ','.join(['?' for x in combat['tank_list']]), base_tup + tuple(combat['tank_list'])).fetchall()
            healerDeath_list = conn_execute(self.conn, select_str % ','.join(['?' for x in combat['healer_list']]), base_tup + tuple(combat['healer_list'])).fetchall()
            
            raidTotal_int = len(combat['dps_list']) + len(combat['tank_list']) + len(combat['healer_list'])
            deadTotal_int = len(dpsDeath_list) + len(tankDeath_list) + len(healerDeath_list)
            
            if raidTotal_int and float(deadTotal_int) / raidTotal_int > 0.5:
                id_min = min(tankDeath_list[0]['start_event_id'], healerDeath_list[0]['start_event_id'], lastHeal_wound[-1]['start_event_id'])
                
                conn_execute(self.conn, '''update event set wipe = 1 where id >= ? and id <= ?''', (id_min, combat['end_event_id']))
WipeRun() # This sets up the dict of runners so that we don't have to call them in __init__


class WoundRun(DataRun):
    def __init__(self):
        DataRun.__init__(self, ['CombatRun', 'FakeDeathRun'], ['wound'])
        
    def impl(self, options):
        for combat in conn_execute(self.conn, '''select * from combat order by start_event_id''').fetchall():
            wound_manager = DurationManager(self.conn, 'wound', [('combat_id', 'int'), ('destType', 'str'), ('destName', 'str')], [('amount', 'int default 0'), ('direction', 'int default 0'), ('dead', 'int default 0')])
            
            for event in basicparse.getEventData(self.conn, orderBy='id', destType='PC', suffix=('_DAMAGE', '_HEAL', '_DIED', '_RESURRECT')).fetchall():
                if event['destType'] == 'PC':
                    if event['suffix'] == '_DAMAGE' and event['amount'] > 0:
                        wound = wound_manager.get(event, value=(0, 0, 0))
                        wound_manager.add(event, value=(wound['amount'] + event['amount'] - event['extra'], -1, 0))

                    elif event['suffix'] == '_HEAL' and event['amount'] > 0:
                        # We don't set direction=1 on HOTs because we only
                        # want direction to track actions, not automatic
                        # effects.  We should probably also screen out spells
                        # like Earth Shield.  FIXME
                        if event['prefix'] == 'SPELL_PERIODIC':
                            direction = 0
                        else:
                            direction = 1
                            
                        if event['extra'] > 0:
                            wound_manager.add(event, value=(0, direction, 0))
                        else:
                            wound = wound_manager.get(event, value=(0, 0, 0))
                            wound_manager.add(event, value=(wound['amount'] - event['amount'], direction, 0))

                    elif event['suffix'] == '_DIED' and event['fakeDeath'] != 1:
                        wound_manager.add(event, value=(0, -1, 1))
                        
                    elif event['suffix'] == '_RESURRECT':
                        wound_manager.add(event, value=(0, 1, 0))
                        #wound_manager.remove(event)
                        
            event = basicparse.getEventData(self.conn, id=combat['end_event_id']).fetchone()
            wound_manager.close(event)
WoundRun() # This sets up the dict of runners so that we don't have to call them in __init__


class CastRun(DataRun):
    def __init__(self):
        DataRun.__init__(self, ['CombatRun'], ['cast'])
        
    def impl(self, options):
        for combat in conn_execute(self.conn, '''select * from combat order by start_event_id''').fetchall():
            cast_manager = DurationManager(self.conn, 'cast', [('combat_id', 'int'), ('sourceType', 'str'), ('sourceName', 'str')], [('spellName', 'str'), ('spellId', 'int'), ('destType', 'str'), ('destName', 'str')])
            
            for event in basicparse.getEventData(self.conn, orderBy='id', suffix=('_CAST_START', '_CAST_SUCCESS', '_CAST_FAILED')).fetchall():
                if event['suffix'] == '_CAST_START':
                    cast_manager.add(event)
                elif event['suffix'] == '_CAST_SUCCESS' or event['suffix'] == '_CAST_FAILED':
                    cast_manager.remove(event)
                    
            event = basicparse.getEventData(self.conn, id=combat['end_event_id']).fetchone()
            cast_manager.close(event)
CastRun() # This sets up the dict of runners so that we don't have to call them in __init__


class AuraRun(DataRun):
    def __init__(self):
        DataRun.__init__(self, ['CombatRun'], ['aura'])
        
    def impl(self, options):
        print datetime.datetime.now(), "Calculating auras..."
        
        for combat in conn_execute(self.conn, '''select * from combat order by start_event_id''').fetchall():
            aura_manager = DurationManager(self.conn, 'aura', [('combat_id', 'int'), ('destType', 'str'), ('destName', 'str'), ('spellName', 'str'), ('spellId', 'str')], [('sourceType', 'str'), ('sourceName', 'str')])
            
            for event in basicparse.getEventData(self.conn, orderBy='id', suffix=('_AURA_APPLIED', '_AURA_REMOVED')).fetchall():
                if event['eventType'] == 'SPELL_AURA_APPLIED':
                    aura_manager.add(event)
                elif event['eventType'] == 'SPELL_AURA_REMOVED':
                    aura_manager.remove(event)

            event = basicparse.getEventData(self.conn, id=combat['end_event_id']).fetchone()
            aura_manager.close(event)
AuraRun() # This sets up the dict of runners so that we don't have to call them in __init__


if __name__ == "__main__":
    WipeRun().main(sys.argv[1:])
    #options, arguments = usage(sys.argv[1:])
    #sys.exit(main(sys.argv[1:], options, arguments) or 0)

# eof