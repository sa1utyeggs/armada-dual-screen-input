# SPDX-License-Identifier: GPL-2.0-only
import unittest

from trace_reads import decode


def packet(values, start=1.):
    return [f'irq-ft5452-1 [000] {start+i*.0001:.6f}: regmap_reg_read: 1-0038 reg={i:x} val={v:x}'
            for i, v in enumerate(values)]


class TraceReadTests(unittest.TestCase):
    def test_contact_coordinates_and_ids_are_decoded_before_input_transforms(self):
        values = [0, 0, 2, 0x81, 0x23, 0x04, 0x56, 0, 0, 0x87, 0x89, 0x1a, 0xbc, 0, 0]
        frame, = decode(packet(values))['frames']
        self.assertTrue(frame['sequential'])
        self.assertFalse(frame['complete'])
        self.assertEqual(frame['reported_contacts'], 2)
        self.assertEqual(frame['contacts'], [dict(id=0, event=2, x=0x123, y=0x456, weight=0, misc=0),
                                             dict(id=1, event=2, x=0x789, y=0xabc, weight=0, misc=0)])
        self.assertAlmostEqual(frame['duration_ms'], 1.4)

    def test_missing_or_repeated_registers_are_visible_and_not_decoded_as_a_packet(self):
        for lines in (packet([0, 0, 1, 0, 1, 0, 2, 0, 0])[1:],
                      packet([0, 0, 1, 0, 1, 0, 2, 0, 0])[:4]+packet([0, 0, 1])[2:]):
            frame, = decode(lines)['frames']
            self.assertFalse(frame['sequential'])
            self.assertEqual(frame['contacts'], [])

    def test_boundaries_reserved_entries_and_failed_transfers_are_preserved(self):
        lines = packet([0, 0, 0, 0xc0, 0, 0, 0, 0, 0])
        lines += ['task [000] 1.01: i2c_result: i2c-1 n=2 ret=-110']
        lines += packet([0, 0, 1, 0, 5, 0, 6, 0, 0], start=2.)
        result = decode(lines)
        self.assertEqual(len(result['frames']), 2)
        self.assertEqual(result['frames'][0]['contacts'], [])
        self.assertEqual(result['frames'][1]['contacts'], [dict(id=0, event=0, x=5, y=6, weight=0, misc=0)])
        self.assertEqual(result['transfers'], [dict(messages=2, returned=-110)])

    def test_only_a_full_sequential_33_register_read_is_complete(self):
        complete, short = decode(packet([0]*33)+packet([0]*32, start=2.))['frames']
        self.assertTrue(complete['complete'])
        self.assertFalse(short['complete'])


    def test_bulk_groups_reconstruct_a_frame_and_include_the_first_read_time(self):
        lines = ['task [000] 1.000: regmap_hw_read_start: 1-0038 reg=0 count=3']
        values = [0, 0, 1, 0x81, 2, 3, 4, 50, 96]+[255]*24
        for offset, count in ((0, 3), (3, 6), (9, 6), (15, 6), (21, 6), (27, 6)):
            data = ' '.join(f'{v:02x}' for v in values[offset:offset+count])
            lines.append(f'task [000] {1.001+offset*.0001:.6f}: regmap_bulk_read: 1-0038 reg={offset:x} val={data}')
        frame, = decode(lines)['frames']
        self.assertTrue(frame['complete'])
        self.assertEqual(frame['bytes'], values)
        self.assertEqual(frame['contacts'], [dict(id=0, event=2, x=258, y=772, weight=50, misc=96)])
        self.assertAlmostEqual(frame['duration_ms'], 3.7)

    def test_bulk_mirror_does_not_hide_a_later_identical_real_read(self):
        values = [0]*33
        lines = ['task [000] 0.999: regmap_hw_read_start: 1-0038 reg=0 count=1']+packet(values)
        lines += ['task [000] 1.004: regmap_bulk_read: 1-0038 reg=0 val='+('00'*33)]
        lines += ['task [000] 1.999: regmap_hw_read_start: 1-0038 reg=0 count=33',
                  'task [000] 2.001: regmap_bulk_read: 1-0038 reg=0 val='+('00'*33)]
        first, second = decode(lines)['frames']
        self.assertTrue(first['complete'])
        self.assertTrue(second['complete'])
        self.assertEqual((first['bulk_mirrors'], second['bulk_mirrors']), (1, 0))
        self.assertAlmostEqual(second['duration_ms'], 2.)

    def test_actual_i2c_message_length_is_retained_separately_from_regmap_groups(self):
        result = decode(['task [000] 1.234: i2c_read: i2c-1 #1 a=038 f=0001 l=33'])
        self.assertEqual(result['reads'], [dict(at=1.234, bus=1, address=56, length=33)])

    def test_i2c_write_pointer_and_reply_retain_exact_messages_before_regmap_decoding(self):
        # The kernel uses [%*phD], with hyphen-separated bytes, for both events.
        values = [0, 0, 2, 0x81, 0x2b, 0, 0xf8, 50, 0xb0,
                  0x80, 0xff, 0x13, 0x72, 54, 0x70]+[255]*18
        payload = '-'.join(f'{value:02x}' for value in values)
        lines = ['irq [000] 1.000: i2c_write: i2c-1 #0 a=038 f=0000 l=1 [00]',
                 'irq [000] 1.001: i2c_read: i2c-1 #1 a=038 f=0001 l=33',
                 f'irq [000] 1.004: i2c_reply: i2c-1 #1 a=038 f=0001 l=33 [{payload}]',
                 'irq [000] 1.005: i2c_result: i2c-1 n=2 ret=2']
        lines += packet(values, start=1.006)
        result = decode(lines)
        self.assertEqual(result['messages'][0], dict(at=1., kind='write', bus=1,
                         message=0, address=56, flags=0, length=1, bytes=[0],
                         payload='00', payload_complete=True))
        self.assertEqual(result['messages'][1], dict(at=1.004, kind='reply', bus=1,
                         message=1, address=56, flags=1, length=33, bytes=values,
                         payload=payload, payload_complete=True))
        # I2C data is retained independently; it does not create an extra frame.
        frame, = result['frames']
        self.assertEqual(frame['bytes'], values)
        self.assertEqual([(c['id'], c['x'], c['y']) for c in frame['contacts']],
                         [(0, 299, 248), (1, 255, 882)])
        self.assertEqual(result['reads'], [dict(at=1.001, bus=1, address=56, length=33)])
        self.assertEqual(result['transfers'], [dict(messages=2, returned=2)])

    def test_incomplete_or_malformed_i2c_payload_cannot_claim_complete_reply(self):
        result = decode([
            'task [000] 1.0: i2c_reply: i2c-1 #1 a=038 f=0001 l=3 [01-02]',
            'task [000] 2.0: i2c_reply: i2c-1 #1 a=038 f=0001 l=2 [01-02',
            'task [000] 3.0: i2c_reply: i2c-1 #1 a=038 f=0001 l=2 [01-0z]',
            'task [000] 4.0: i2c_reply: i2c-1 #1 a=038 f=0001 l=2',
            'task [000] 5.0: i2c_reply: i2c-1 #1 a=038 f=0001 l=1 [01-02]',
        ])
        messages = result['messages']
        self.assertEqual(len(messages), 5)
        self.assertTrue(all(not message['payload_complete'] for message in messages))
        self.assertEqual([message['bytes'] for message in messages],
                         [[1, 2], [1, 2], [], [], [1, 2]])
        self.assertEqual(messages[2]['payload'], '01-0z')
        self.assertEqual(result['frames'], [])

    def test_interleaved_buses_addresses_indices_and_flags_are_not_combined(self):
        result = decode([
            'task [000] 1.0: i2c_write: i2c-1 #0 a=038 f=0000 l=1 [00]',
            'task [000] 1.1: i2c_write: i2c-4 #0 a=038 f=0010 l=1 [a6]',
            'task [000] 1.2: i2c_reply: i2c-1 #9 a=039 f=0401 l=1 [99]',
            'task [000] 1.3: i2c_reply: i2c-4 #1 a=038 f=0011 l=1 [22]',
            'task [000] 1.4: i2c_reply: i2c-1 #1 a=038 f=0001 l=1 [11]',
            'task [000] 1.5: i2c_reply: i2c-1 #3 a=038 f=0001 l=0 []',
        ])
        self.assertEqual([(m['bus'], m['address'], m['message'], m['flags'], m['bytes'])
                          for m in result['messages']],
                         [(1, 56, 0, 0, [0]), (4, 56, 0, 16, [166]),
                          (1, 57, 9, 1025, [153]), (4, 56, 1, 17, [34]),
                          (1, 56, 1, 1, [17]), (1, 56, 3, 1, [])])
        self.assertTrue(all(m['payload_complete'] for m in result['messages']))
        self.assertEqual(result['frames'], [])


if __name__ == '__main__':
    unittest.main()
