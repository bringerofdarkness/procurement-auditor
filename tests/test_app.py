"""Run the Streamlit screen headlessly."""

from streamlit.testing.v1 import AppTest


def open_app():
    app = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not app.exception
    return app


def test_app_shows_full_score():
    assert open_app().metric[0].value == "10 / 10"


def test_person_can_finish_a_review_on_screen():
    app = open_app()
    app.selectbox(key="selected_document").select("supplier-pack-07.pdf").run()
    app.text_input[0].input("Rahima")
    app.button(key="submit_review").click().run()

    assert not app.exception
    assert any("Decided by Rahima" in item.value for item in app.markdown)
