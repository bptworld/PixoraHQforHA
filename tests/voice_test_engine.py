"""Offline acceptance cases, including the user's exact six requests."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice/custom_components/pixora_voice'))
from engine import Entity,answer,duration_answer
from datetime import datetime,timedelta,timezone


def catalog():
    return [
        Entity('lock.front','Front door','unlocked',{},'Entry'),
        Entity('binary_sensor.front','Front door contact sensor','off',{'device_class':'door'},'Entry'),
        Entity('binary_sensor.kitchen','Kitchen contact','on',{'device_class':'window'},'Kitchen'),
        Entity('binary_sensor.bedroom','Bedroom contact','off',{'device_class':'window'},'Bedroom'),
        Entity('climate.downstairs','Downstairs thermostat','heat',{'hvac_action':'idle','current_temperature':67},'Living Room'),
        Entity('sensor.living_temp','Living Room air sensor','68',{'device_class':'temperature','unit_of_measurement':'°F'},'Living Room'),
        Entity('sensor.kitchen_temp','Kitchen air sensor','71',{'device_class':'temperature','unit_of_measurement':'°F'},'Kitchen'),
        Entity('light.living_ceiling','Ceiling light','off',{'brightness':128},'Living Room'),
        Entity('light.kitchen_ceiling','Ceiling light','on',{'brightness':128},'Kitchen'),
        Entity('light.kitchen_counter','Counter light','on',{'brightness':128},'Kitchen'),
        Entity('switch.kitchen','Kitchen coffee','on',{},'Kitchen'),
    ]


class MatchingTests(unittest.TestCase):
    def test_added_phrasings_keep_capability_filtering(self):
        for text in ['Do you know if the front door is open?','Can you check if the front door is ajar?']:
            self.assertEqual(answer(text,catalog()).entities,['binary_sensor.front'])
        self.assertIn('68',answer('Tell me the temp in this room',catalog(),'Living Room').speech)

    def test_unqualified_temperature_never_substitutes_other_room(self):
        self.assertEqual(answer("What's the temperature?",catalog(),'Living Room').entities,['sensor.living_temp'])
        self.assertEqual(answer("What's the temperature?",catalog(),'Bedroom').kind,'not_found')
        self.assertEqual(answer("What's the temperature?",catalog()).kind,'clarify')

    def test_duration_is_current_report_not_invented_history(self):
        now=datetime.now(timezone.utc);entity=catalog()[1]
        self.assertIn('reliable time',duration_answer(entity,now).speech)
        entity.last_changed=now-timedelta(minutes=4)
        self.assertIn('reporting closed for 4 minutes',duration_answer(entity,now).speech)
        entity.state='unavailable';self.assertIn('unavailable',duration_answer(entity,now).speech)
        entity.state='off';entity.last_changed=now+timedelta(minutes=1)
        self.assertIn('reliable time',duration_answer(entity,now).speech)
    def test_front_open_uses_contact_even_when_lock_has_exact_name(self):
        r=answer('Is the front door open?',catalog());self.assertEqual(r.entities,['binary_sensor.front']);self.assertIn('closed',r.speech);self.assertIsNone(r.command)

    def test_locked_uses_lock(self):
        r=answer('Is the front door locked?',catalog());self.assertEqual(r.entities,['lock.front']);self.assertIn('unlocked',r.speech)

    def test_windows_uses_device_class_even_when_not_in_name(self):
        r=answer('Are there any windows open?',catalog(),'Living Room');self.assertIn('kitchen window',r.speech);self.assertNotIn('Front door',r.speech);self.assertEqual(len(r.entities),2)

    def test_heat_mode_does_not_mean_heat_running(self):
        r=answer('Is the heat on?',catalog(),'Living Room');self.assertEqual(r.entities,['climate.downstairs']);self.assertIn('not heating',r.speech)
        es=catalog();es[4].attributes['hvac_action']='heating';self.assertIn('actively heating',answer('Is the heat on?',es).speech)
        es[4].attributes.pop('hvac_action');self.assertIn('does not report',answer('Is the heat on?',es).speech)

    def test_here_uses_speaker_room_and_prefers_actual_sensor(self):
        r=answer("What's the temperature in here?",catalog(),'Living Room');self.assertEqual(r.entities,['sensor.living_temp']);self.assertIn('68',r.speech)
        self.assertEqual(answer("What's the temperature in here?",catalog()).kind,'clarify')

    def test_unqualified_light_uses_listening_speaker_area(self):
        r=answer('Turn on the ceiling light',catalog(),'Living Room');self.assertEqual(r.entities,['light.living_ceiling']);self.assertEqual(r.command['service'],'turn_on')
        r=answer('Turn on the ceiling light',catalog(),'Kitchen');self.assertEqual(r.entities,['light.kitchen_ceiling'])
        r=answer('Turn on the ceiling light',catalog(),'Bedroom');self.assertEqual(r.kind,'not_found');self.assertIsNone(r.command)

    def test_explicit_room_overrides_speaker_and_all_means_whole_group(self):
        r=answer('Turn off all kitchen lights',catalog(),'Living Room');self.assertEqual(set(r.entities),{'light.kitchen_ceiling','light.kitchen_counter'});self.assertEqual(r.command['domain'],'light');self.assertEqual(r.command['service'],'turn_off');self.assertIsInstance(r.command['data']['entity_id'],list)

    def test_lock_cannot_substitute_when_contact_missing(self):
        es=[e for e in catalog() if e.entity_id!='binary_sensor.front'];r=answer('Is the front door open?',es);self.assertEqual(r.kind,'not_found')

    def test_ambiguous_no_room_does_not_command(self):
        r=answer('Turn on the ceiling light',catalog());self.assertEqual(r.kind,'clarify');self.assertIsNone(r.command)

    def test_unavailable_contact_is_not_closed_or_replaced_by_lock(self):
        es=catalog();es[1].state='unavailable';r=answer('Is the front door open?',es);self.assertEqual(r.entities,['binary_sensor.front']);self.assertIn('unavailable',r.speech);self.assertNotIn('closed',r.speech)

    def test_unknown_windows_are_disclosed(self):
        es=catalog();es[2].state='unavailable';r=answer('Are any windows open?',es);self.assertIn("can't check Kitchen window",r.speech)

    def test_hidden_from_assist_never_matched(self):
        es=catalog();es[1].exposed=False;self.assertEqual(answer('Is the front door open?',es).kind,'not_found')

    def test_aliases(self):
        es=catalog();es[1].aliases=['main entrance'];self.assertEqual(answer('Is the main entrance open?',es).entities,['binary_sensor.front'])

    def test_brightness(self):
        r=answer('Set the ceiling light to 40 percent',catalog(),'Kitchen');self.assertEqual(r.command['data']['brightness_pct'],40)

    def test_security_and_negation_never_accidentally_execute(self):
        for text in ['Unlock the front door','Do not turn on the ceiling light','What happens if I turn on the ceiling light?','Turn off the ceiling light when motion stops','Turn on the ceiling light and the counter light','Turn on the ceiling light except in kitchen','Set the ceiling light to 999 percent']:
            with self.subTest(text=text):self.assertIsNone(answer(text,catalog(),'Kitchen').command)

    def test_missing_room_never_selects_other_room_for_control(self):
        self.assertIsNone(answer('Turn off all lights',catalog(),'Bedroom').command)

    def test_yes_no_replies_preserve_unknown_and_opposite_states(self):
        es=catalog()
        self.assertTrue(answer('Is the front door open?',es).speech.startswith('No,'))
        self.assertTrue(answer('Is the front door closed?',es).speech.startswith('Yes,'))
        self.assertTrue(answer('Is the front door unlocked?',es).speech.startswith('Yes,'))
        self.assertTrue(answer('Is the front door locked?',es).speech.startswith('No,'))
        es[1].state='unavailable'
        reply=answer('Is the front door open?',es).speech
        self.assertNotIn('Yes,',reply);self.assertNotIn('No,',reply);self.assertIn('unavailable',reply)
        es[4].attributes.pop('hvac_action',None)
        reply=answer('Is the heat on?',es).speech
        self.assertNotIn('Yes,',reply);self.assertNotIn('No,',reply);self.assertIn('does not report',reply)

    def test_spoken_names_and_readings_are_natural(self):
        es=catalog();es[1].name='Living Room Front Door Sensor';es[1].area='Living Room'
        self.assertEqual(answer('Is the front door open?',es).speech,'No, the front door is closed.')
        self.assertEqual(answer('Are any windows open?', [e for e in es if e.entity_id!='binary_sensor.kitchen']).speech,'All the windows I can check are closed.')
        self.assertEqual(answer("What's the temperature in here?",es,'Living Room').speech,"It's 68 degrees Fahrenheit in Living Room.")
        self.assertEqual(answer('Turn on the ceiling light',es,'Living Room').speech,'Okay, turning on Ceiling light.')

    def test_polite_requests_and_natural_readings(self):
        for text in ['Could you please turn on the ceiling light','Can you turn the ceiling light on','Please turn on the ceiling light']:
            self.assertEqual(answer(text,catalog(),'Kitchen').command['data']['entity_id'],'light.kitchen_ceiling')
        self.assertIn('closed',answer('Tell me if the front door is open',catalog()).speech)
        self.assertIn('68',answer('How warm is it in this room?',catalog(),'Living Room').speech)

    def test_spoken_brightness_and_negation(self):
        self.assertEqual(answer('Could you set the ceiling light to forty five percent',catalog(),'Kitchen').command['data']['brightness_pct'],45)
        for text in ['Could you not turn on the ceiling light','Set the ceiling light to forty percent if it is dark','Dim the ceiling light to ten percent and turn off the fan']:
            self.assertIsNone(answer(text,catalog(),'Kitchen').command)

    def test_group_status_filters_and_counts(self):
        es=catalog();es[8].state='off'
        r=answer('Which kitchen lights are on?',es)
        self.assertEqual(r.speech,'The counter light is on.')
        self.assertIn('1 device is on',answer('How many kitchen lights are on?',es).speech)
        es[9].state='unavailable'
        self.assertIn("can't confirm",answer('Are all kitchen lights off?',es).speech)

    def test_here_groups_never_leak_into_other_rooms(self):
        r=answer('Are any lights on in this room?',catalog(),'Living Room')
        self.assertEqual(r.entities,['light.living_ceiling']);self.assertIn('None',r.speech)

    def test_cooling_uses_actual_action(self):
        es=catalog();es[4].state='cool';es[4].attributes['hvac_action']='idle'
        self.assertIn('not cooling',answer('Is the air conditioning on?',es).speech)
        es[4].attributes['hvac_action']='cooling'
        self.assertIn('is cooling',answer('Is the air conditioning on?',es).speech)

    def test_unsupported_pronoun_command_never_guesses(self):
        r=answer('Turn it off',[catalog()[7]],'Living Room')
        self.assertEqual(r.kind,'clarify');self.assertIsNone(r.command)

    def test_numbered_rooms_stay_distinct(self):
        es=[Entity('light.one','Room 1 ceiling light','on',{},'Room 1'),Entity('light.two','Room 2 ceiling light','off',{},'Room 2')]
        self.assertEqual(answer('Turn on all Room 2 lights',es).entities,['light.two'])
        self.assertEqual(answer('Which Room 1 lights are on?',es).entities,['light.one'])

    def test_plural_room_lights_work_without_all(self):
        self.assertEqual(set(answer('Turn off kitchen lights',catalog(),'Living Room').entities),{'light.kitchen_ceiling','light.kitchen_counter'})
        self.assertEqual(set(answer('Turn off the lights',catalog(),'Kitchen').entities),{'light.kitchen_ceiling','light.kitchen_counter'})
        self.assertIsNone(answer('Turn off the lights',catalog()).command)

    def test_lazy_ha_name_does_not_break_unrelated_queries(self):
        class ComputedName:
            def __str__(self):return 'Unrelated light'
        es=catalog()+[Entity('light.computed',ComputedName(),'off',{},'Office')]
        self.assertEqual(answer('Which kitchen lights are on?',es).entities,['light.kitchen_ceiling','light.kitchen_counter'])

    def test_no_long_or_empty_input(self):
        for text in ['',None,'a'*501]:self.assertEqual(answer(text,catalog()).kind,'unsupported')

if __name__=='__main__':unittest.main()
