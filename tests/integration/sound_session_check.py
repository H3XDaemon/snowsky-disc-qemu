"""Reviewed sound settings through the persistent facade on a disposable guest."""
from controller import DeviceConfig, DiscSession


def check():
    with DiscSession(DeviceConfig('127.0.0.1', http_port=12103)) as session:
        session.connect()
        assert session.wait_ready(35), session.snapshot()
        initial = session.sound_settings()
        assert initial.status == 'observed', initial
        original = initial.confirmation['settings']
        current = dict(original)
        try:
            for name, values in [('gain', (0, 1)), ('balance', (-20, 0, 20)),
                                 ('filter', tuple(range(6))), ('dre', (0, 1))]:
                for value in values:
                    result = session.set_sound_setting(name, value, expected=current[name])
                    assert result.status in ('confirmed', 'already_satisfied'), result
                    assert result.confirmation == {'name': name, 'value': value}, result
                    current[name] = value
                    observed = session.sound_settings()
                    assert observed.status == 'observed', observed
                    assert observed.confirmation['settings'][name] == value, observed
            rejected = session.set_sound_setting('balance', 0, expected=-20)
            assert rejected.status == 'not_sent' and not rejected.mutation_attempted, rejected
        finally:
            for name, value in original.items():
                observed = session.sound_settings()
                assert observed.status == 'observed', observed
                result = session.set_sound_setting(name, value, expected=observed.confirmation['settings'][name])
                assert result.status in ('confirmed', 'already_satisfied'), result
        print('Persistent sound settings: gain, balance, six filters and DRE confirmed/restored', flush=True)


if __name__ == '__main__':
    check()
