import asyncio

import pytest
from fastapi import HTTPException

from api.users import UserSettingsUpdate, get_user, update_user_settings
from models import User


def _user(db, *, role='user'):
    user = User(id='settings-user', username='settings-user', email='settings@example.com',
                hashed_password='not-used-in-test', role=role, tenant_id='test_tenant', settings={"language": 'zh-CN'})
    db.add(user)
    db.commit()
    return user


def test_personal_settings_save_and_profile_are_accessible_to_owner(db):
    user = _user(db)
    result = asyncio.run(update_user_settings(user.id, UserSettingsUpdate(settings={"language": 'en'}), db, user))
    assert result['settings']['language'] == 'en'
    assert asyncio.run(get_user(user.id, db, user))['settings']['language'] == 'en'


@pytest.mark.parametrize('role', ['user', 'tenant_admin'])
def test_personal_settings_cannot_be_changed_by_other_user_even_admin(db, role):
    user = _user(db, role=role)
    with pytest.raises(HTTPException) as error:
        asyncio.run(update_user_settings('another-user', UserSettingsUpdate(settings={"language": 'en'}), db, user))
    assert error.value.status_code == 403
    assert user.settings['language'] == 'zh-CN'


def test_member_cannot_read_other_users_profile(db):
    user = _user(db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_user('another-user', db, user))
    assert error.value.status_code == 403


def test_admin_profile_not_found_preserves_404(db):
    user = _user(db, role='tenant_admin')
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_user('missing-user', db, user))
    assert error.value.status_code == 404
