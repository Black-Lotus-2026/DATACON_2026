from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from datacon_agent.agent import AgentSettings, ChemExtractionAgent
from datacon_agent.domains import DOMAINS, get_domain
from datacon_agent.normalize import samples_to_frame


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="DataCon Agent", layout="wide")
    st.title("DataCon Agent")

    with st.sidebar:
        domain_key = st.selectbox("Domain", sorted(DOMAINS), format_func=lambda key: DOMAINS[key].title)
        model = st.text_input("Model", value="gpt-4.1")
        review_model = st.text_input("Review model", value="")
        base_url = st.text_input("Base URL", value="")
        pages_per_window = st.number_input("Pages per pass", min_value=1, max_value=10, value=4)
        send_images = st.toggle("Page images", value=True)
        review = st.toggle("Review pass", value=True)
        max_pages = st.number_input("Max pages", min_value=0, value=0)

    uploaded = st.file_uploader("PDF", type=["pdf"])
    run = st.button("Extract", type="primary", disabled=uploaded is None)

    if run and uploaded is not None:
        domain = get_domain(domain_key)
        settings = AgentSettings(
            model=model,
            review_model=review_model or None,
            base_url=base_url or None,
            pages_per_window=int(pages_per_window),
            render_pages=send_images,
            review_candidates=review,
            max_pages=int(max_pages) or None,
        )
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / uploaded.name
            pdf_path.write_bytes(uploaded.getvalue())
            agent = ChemExtractionAgent(domain, settings=settings)
            with st.spinner("Extracting"):
                samples = agent.extract_pdf(pdf_path)
            frame = samples_to_frame(domain, samples, pdf_name=uploaded.name)
            show_result(frame)


def show_result(frame: pd.DataFrame) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.download_button(
        "Download CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="prediction.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
