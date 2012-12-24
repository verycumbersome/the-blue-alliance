import datetime
import logging
import os

from google.appengine.api import taskqueue
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.api import urlfetch

from helpers.event_team_manipulator import EventTeamManipulator
from helpers.team_manipulator import TeamManipulator
from helpers.opr_helper import OprHelper

from models.event import Event
from models.event_team import EventTeam
from models.match import Match
from models.team import Team
from models.sitevar import Sitevar


class EventTeamUpdate(webapp.RequestHandler):
    """
    Task that adds to the EventTeam index for an Event.
    Can only update or delete EventTeams for unregistered teams. 
    """
    def get(self, event_key):
        event = Event.get_by_id(event_key)
        team_ids = set()
        
        # Add teams from Matches
        for match in Match.query(Match.event == event.key).fetch(1000):
            for team in match.team_key_names:
                team_ids.add(team)
        
        teams = TeamManipulator.createOrUpdate([Team(
            id = team_id,
            team_number = int(team_id[3:]))
            for team_id in team_ids])

        if teams:
            event_teams = EventTeamManipulator.createOrUpdate([EventTeam(
                id = event_key + "_" + team.key.id(),
                event = event.key,
                team = team.key,
                year = event.year)
                for team in teams])
        else:
            event_teams = None
        
        template_values = {
            'event_teams': event_teams,
        }
        
        path = os.path.join(os.path.dirname(__file__), '../templates/math/eventteam_update_do.html')
        self.response.out.write(template.render(path, template_values))
        
class EventTeamUpdateEnqueue(webapp.RequestHandler):
    """
    Handles enqueing building attendance for Events.
    """
    def get(self, when):
        if when == "all":
            event_keys = Event.query().fetch(10000, keys_only=True)
        else:
            event_keys = Event.query(Event.year == int(when)).fetch(10000, keys_only=True)
        
        for event_key in event_keys:
            taskqueue.add(
                url='/tasks/math/do/eventteam_update/' + event_key.id(),
                method='GET')
        
        template_values = {
            'event_keys': event_keys,
        }
        
        path = os.path.join(os.path.dirname(__file__), '../templates/math/eventteam_update_enqueue.html')
        self.response.out.write(template.render(path, template_values))

class EventOprDo(webapp.RequestHandler):
    """
    Calculates the opr for an event
    """
    def get(self, event_key):
        opr = []
        teams = []
        oprs = []
        event = Event.get_by_id(event_key)
        if Match.query(Match.event == event.key).count() > 0:
            try:
                opr,teams = OprHelper.opr(event_key)
                oprs.append((opr,teams))
                event.oprs = opr
                event.opr_teams = teams
                event.put()
            except Exception, e:
                logging.error("OPR error on event %s. %s" % (event_key, e))

        logging.info(oprs)

        template_values = {
            'oprs': oprs,
        }
        
        path = os.path.join(os.path.dirname(__file__), '../templates/math/event_opr_do.html')
        self.response.out.write(template.render(path, template_values))

    def post(self):
        self.get()

class EventOprEnqueue(webapp.RequestHandler):
    """
    Enqueues OPR calculation
    """
    def get(self, when):
        if when == "now":
            events = Event.query(Event.end_date <= datetime.datetime.today() + datetime.timedelta(days=4))
            events = Event.query(Event.end_date >= datetime.datetime.today() - datetime.timedelta(days=1))
        else:
            events = Event.query(Event.year == int(when))
        
        events = events.fetch(500)
        
        for event in events:
            taskqueue.add(
                url='/tasks/math/do/event_opr/' + event.key_name,
                method='GET')
        
        template_values = {
            'event_count': len(events),
            'year': when
        }
        
        path = os.path.join(os.path.dirname(__file__), '../templates/math/event_opr_enqueue.html')
        self.response.out.write(template.render(path, template_values))

class FirebasePushDo(webapp.RequestHandler):
    """
    Pushes data to Firebase
    """
    FIREBASE_URL = 'https://thebluealliance.firebaseio.com/{}.json?auth={}'

    def get(self):
        key = self.request.get('key')
        payload_json = self.request.get('payload_json')
        
        firebase_secrets = Sitevar.get_by_id("firebase.secrets")
        if firebase_secrets == None:
            raise Exception("Missing sitevar: firebase.secrets. Can't write to Firebase.")
        FIREBASE_SECRET = firebase_secrets.contents['FIREBASE_SECRET']
        
        url = self.FIREBASE_URL.format(key, FIREBASE_SECRET)
        result = urlfetch.fetch(url, payload_json, 'PUT')
        if result.status_code == 200:
            logging.info("Sucessfully pushed data to Firebase. {}".format(key))
        else:
            logging.warning("Error pushing the a match to Firebase: {}. ERROR {}: {}".format(key, result.status_code, result.content))
