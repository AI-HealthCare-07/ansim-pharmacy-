from app.services.ingredient_status import DurLink, IngredientState, decide


def _d(**kw):
    base = dict(has_hira_code=False, permit_ingredient_count=0, linked_ingredient_count=0,
                has_permit_text=True, has_age=True, has_pregnancy_info=True)
    base.update(kw)
    return decide(**base)


def test_hira_code_full_link():
    s = _d(has_hira_code=True, permit_ingredient_count=1, linked_ingredient_count=1)
    assert s.ingredient is IngredientState.CONFIRMED_HIRA and s.dur_link is DurLink.FULL
    assert s.age_rules_enabled and s.pregnancy_rules_enabled


def test_no_hira_code_but_permit_ingredient():
    s = _d(permit_ingredient_count=2, linked_ingredient_count=0)
    assert s.ingredient is IngredientState.CONFIRMED_MFDS_ONLY and s.dur_link is DurLink.NONE
    assert not s.allow_ingredient_judgement and s.show_permit_text
    assert "비급여라는 뜻은 아니에요" in s.coverage_note


def test_partial_link_blocks_personal_rules():
    s = _d(permit_ingredient_count=2, linked_ingredient_count=1)
    assert s.dur_link is DurLink.PARTIAL and s.allow_ingredient_judgement
    assert not s.age_rules_enabled and not s.pregnancy_rules_enabled


def test_unresolved_still_shows_permit_text():
    s = _d()
    assert s.ingredient is IngredientState.UNRESOLVED and s.show_permit_text
    assert "확인할 수 없어요" in s.dur_note


def test_missing_profile_disables_rules():
    s = _d(has_hira_code=True, permit_ingredient_count=1, linked_ingredient_count=1, has_age=False, has_pregnancy_info=False)
    assert not s.age_rules_enabled and not s.pregnancy_rules_enabled


def test_dur_full_never_says_safe():
    s = _d(has_hira_code=True, permit_ingredient_count=1, linked_ingredient_count=1)
    assert "안전하다는 뜻은 아니에요" in s.dur_note


def test_guidance_items_cover_six_legal_items_and_report_missing():
    from app.services.guidance_items import ITEMS, availability
    assert [i.legal_no for i in ITEMS] == [1, 2, 3, 4, 5, 6]
    a = availability({"item_name": "예시정", "storage_method": "", "nb_doc_data": "<x>"})
    assert a["name_chart"] == "있음" and a["storage"] == "확인할 수 없어요" and a["adverse"] == "있음"
    assert a["relief"] == "확인할 수 없어요"
    assert availability({}, relief_text_verified=True)["relief"] == "있음"
