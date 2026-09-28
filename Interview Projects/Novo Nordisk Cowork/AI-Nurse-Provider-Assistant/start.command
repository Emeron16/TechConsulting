#!/bin/zsh
cd -- "${0:A:h}"
exec /opt/anaconda3/bin/python -m streamlit run app.py
