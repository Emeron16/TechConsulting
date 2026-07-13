import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Load model artifacts ───────────────────────────────────────────────────────
model     = joblib.load('fraud_lr_model.pkl')
features  = joblib.load('model_features.pkl')
threshold = joblib.load('model_threshold.pkl')

scaler     = model.named_steps['scaler']
model_step = model.named_steps['model']

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title='Fraud Detection', page_icon='🔍', layout='wide')
st.title('🔍 Fraud Transaction Detector')
st.markdown('Enter transaction details below to assess fraud risk.')
st.divider()


# ── Preprocessing ──────────────────────────────────────────────────────────────
def preprocess(inputs: dict, feature_cols: list) -> pd.DataFrame:
    inputs['cvv_match_missing']          = 0
    inputs['transaction_amount_missing'] = 0
    inputs['ip_country_match_missing']   = 0

    row = pd.DataFrame([inputs])

    # Apply same log-transform used during training
    log_cols = ['transaction_amount', 'distance_from_home_km',
                'velocity_last_1hr', 'account_age_days']
    for col in log_cols:
        if col in row.columns:
            row[col] = np.log1p(row[col].clip(lower=0))

    row = pd.get_dummies(row, columns=[
        'device_type', 'card_type', 'transaction_channel', 'merchant_category'
    ])
    row = row.reindex(columns=feature_cols, fill_value=0)
    return row


# ── Input form ─────────────────────────────────────────────────────────────────
with st.form('transaction_form'):

    st.subheader('Transaction Details')
    col1, col2, col3 = st.columns(3)

    with col1:
        transaction_amount     = st.number_input('Transaction Amount (USD)', min_value=0.0, value=100.0, step=1.0)
        transaction_hour       = st.slider('Transaction Hour (0–23)', min_value=0, max_value=23, value=12)
        is_weekend             = int(st.checkbox('Weekend Transaction'))
        transaction_channel    = st.selectbox('Transaction Channel', ['atm', 'mobile_app', 'online', 'pos'])
        merchant_category      = st.selectbox('Merchant Category', [
            'fashion', 'electronics', 'entertainment', 'gambling',
            'groceries', 'healthcare', 'retail', 'travel'
        ])

    with col2:
        device_type            = st.selectbox('Device Type', ['desktop', 'mobile', 'tablet', 'unknown'])
        card_type              = st.selectbox('Card Type', ['credit', 'debit', 'prepaid', 'virtual'])
        cvv_match              = st.selectbox('CVV Match', ['Yes', 'No'])
        account_age_days       = st.number_input('Account Age (days)', min_value=1, value=365, step=1)
        amount_deviation_ratio = st.number_input('Amount Deviation Ratio', value=0.0, step=0.01)

    with col3:
        previous_fraud_flags   = st.number_input('Previous Fraud Flags', min_value=0, value=0, step=1)
        failed_auth_attempts   = st.number_input('Failed Auth Attempts', min_value=0, value=0, step=1)
        velocity_last_1hr      = st.number_input('Transactions in Last 1hr', min_value=0, value=1, step=1)
        location_mismatch      = st.selectbox('Location Mismatch', ['No', 'Yes'])
        ip_country_match       = st.selectbox('IP Country Match', ['Yes', 'No'])
        distance_from_home_km  = st.number_input('Distance from Home (km)', min_value=0.0, value=10.0, step=0.1)

    submitted = st.form_submit_button('Assess Fraud Risk', use_container_width=True)


# ── Predict + SHAP ─────────────────────────────────────────────────────────────
if submitted:
    inputs = {
        'transaction_amount':     transaction_amount,
        'transaction_hour':       float(transaction_hour),
        'location_mismatch':      1.0 if location_mismatch == 'Yes' else 0.0,
        'previous_fraud_flags':   float(previous_fraud_flags),
        'velocity_last_1hr':      float(velocity_last_1hr),
        'account_age_days':       float(account_age_days),
        'failed_auth_attempts':   float(failed_auth_attempts),
        'ip_country_match':       1.0 if ip_country_match == 'Yes' else 0.0,
        'amount_deviation_ratio': amount_deviation_ratio,
        'is_weekend':             float(is_weekend),
        'distance_from_home_km':  distance_from_home_km,
        'cvv_match':              1.0 if cvv_match == 'Yes' else 0.0,
        'device_type':            device_type,
        'card_type':              card_type,
        'transaction_channel':    transaction_channel,
        'merchant_category':      merchant_category,
    }

    row        = preprocess(inputs, features)
    proba      = model.predict_proba(row)[0][1]
    prediction = int(proba >= threshold)

    # ── Risk Assessment ────────────────────────────────────────────────────────
    st.divider()
    st.subheader('Risk Assessment')

    res_col1, res_col2, res_col3 = st.columns(3)

    with res_col1:
        st.metric('Fraud Probability', f'{proba:.1%}')

    with res_col2:
        st.metric('Decision Threshold', f'{threshold:.2f}',
                  help='Optimal threshold tuned via Precision-Recall curve to maximise F1 score')

    with res_col3:
        if prediction == 0:
            st.success('### LEGITIMATE')
        else:
            st.error('### FRAUD DETECTED')

    if prediction == 1:
        st.error(f'Transaction flagged as FRAUDULENT — probability {proba:.1%} exceeds tuned threshold of {threshold:.2f}')
    else:
        st.success(f'Transaction appears LEGITIMATE — probability {proba:.1%} is below tuned threshold of {threshold:.2f}')

    # ── SHAP Explanation ───────────────────────────────────────────────────────
    st.divider()
    st.subheader('Why did the model make this decision?')
    st.caption('SHAP values show how much each feature pushed the prediction toward fraud (red) or legitimate (green).')

    row_scaled = scaler.transform(row)

    # For a linear model: contribution = coef * scaled_value
    # This is exactly what SHAP computes for logistic regression
    coefs        = model_step.coef_[0]
    contributions = coefs * row_scaled[0]

    # Sort by absolute contribution and take top 10
    abs_contrib  = np.abs(contributions)
    top_idx      = np.argsort(abs_contrib)[::-1][:10]
    top_features = [features[i]           for i in top_idx]
    top_shap     = [float(contributions[i]) for i in top_idx]
    top_values   = [float(row.values[0][i]) for i in top_idx]

    # Build Plotly horizontal bar chart
    colors = ['#D62B2B' if v > 0 else '#1A7A4A' for v in top_shap]
    labels = [f"input={v:.2f}" for v in top_values]

    fig = go.Figure(go.Bar(
        x=top_shap,
        y=top_features,
        orientation='h',
        marker_color=colors,
        text=labels,
        textposition='outside',
        hovertemplate='<b>%{y}</b><br>SHAP: %{x:.4f}<extra></extra>'
    ))
    fig.add_vline(x=0, line_width=1, line_color='black')
    fig.update_layout(
        title='Top 10 Feature Contributions for This Transaction',
        xaxis_title='SHAP Value  (positive = toward fraud, negative = toward legitimate)',
        yaxis_title='',
        height=450,
        template='plotly_white',
        margin=dict(l=20, r=120, t=50, b=50)
    )
    st.plotly_chart(fig, use_container_width=True)

    # Plain-language summary of top drivers
    st.subheader('Key Drivers')
    shap_df          = pd.DataFrame({'Feature': top_features, 'Value': top_values, 'SHAP Impact': top_shap})
    top_toward_fraud = shap_df[shap_df['SHAP Impact'] > 0].head(3)
    top_toward_legit = shap_df[shap_df['SHAP Impact'] < 0].head(3)

    driver_col1, driver_col2 = st.columns(2)

    with driver_col1:
        st.markdown('**Pushed toward FRAUD 🔴**')
        if top_toward_fraud.empty:
            st.write('No features pushed toward fraud.')
        else:
            for _, r in top_toward_fraud.iterrows():
                st.write(f"• **{r['Feature']}** = {r['Value']:.2f}  (+{r['SHAP Impact']:.3f})")

    with driver_col2:
        st.markdown('**Pushed toward LEGITIMATE 🟢**')
        if top_toward_legit.empty:
            st.write('No features pushed toward legitimate.')
        else:
            for _, r in top_toward_legit.iterrows():
                st.write(f"• **{r['Feature']}** = {r['Value']:.2f}  ({r['SHAP Impact']:.3f})")

    with st.expander('View full preprocessed input sent to model'):
        st.dataframe(row)
