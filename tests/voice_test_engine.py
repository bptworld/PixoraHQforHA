"""Offline acceptance cases, including the user's exact six requests."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice/custom_components/pixora_voice'))
from engine import Entity,answer


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
    def test_front_open_uses_contact_even_when_lock_has_exact_name(self):
        r=answer('Is the front door open?',catalog());self.assertEqual(r.entities,['binary_sensor.front']);self.assertIn('closed',r.speech);self.assertIsNone(r.command)

    def test_locked_uses_lock(self):
        r=answer('Is the front door locked?',catalog());self.assertEqual(r.entities,['lock.front']);self.assertIn('unlocked',r.speech)

    def test_windows_uses_device_class_even_when_not_in_name(self):
        r=answer('Are there any windows open?',catalog(),'Living Room');self.assertIn('Kitchen contact',r.speech);self.assertNotIn('Front door',r.speech);self.assertEqual(len(r.entities),2)

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
        es=catalog();es[2].state='unavailable';r=answer('Are any windows open?',es);self.assertIn('cannot confirm Kitchen contact',r.speech)

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

    def test_no_long_or_empty_input(self):
        for text in ['',None,'a'*501]:self.assertEqual(answer(text,catalog()).kind,'unsupported')

if __name__=='__main__':unittest.main()
