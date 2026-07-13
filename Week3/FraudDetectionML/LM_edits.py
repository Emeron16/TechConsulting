import plotly.graph_objects as go
from skopt import BayesSearchCV
from skopt.space import Real, Integer, Categorical
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline
from sklearn.metrics import (classification_report, roc_auc_score,
                             average_precision_score, precision_recall_curve)
import shap
import joblib

# ══════════════════════════════════════════════════════════════════════════════
# CELL 1 — EDA (paste into a new cell in the EDA section, uses raw df only)
# ══════════════════════════════════════════════════════════════════════════════
eda = df.copy()
eda['Fraud'] = eda['is_fraudulent_transaction'].map({0: 'Legit', 1: 'Fraud'})

# 1. Strip — Transaction Amount by Fraud label (capped at 99th pct)
cap  = eda['transaction_amount'].quantile(0.99)
fig1 = px.strip(
    eda[eda['transaction_amount'] <= cap],
    x='Fraud', y='transaction_amount',
    color='Fraud',
    color_discrete_map={'Legit': '#1f77b4', 'Fraud': '#d62728'},
    title='Transaction Amount by Fraud Label (capped at 99th percentile)',
    labels={'transaction_amount': 'Transaction Amount (USD)', 'Fraud': ''},
    template='plotly_white'
)
fig1.update_traces(jitter=0.4, marker=dict(size=3, opacity=0.4))
fig1.show()

# 2. Box — Distance from Home by Fraud label (log scale to handle extreme outliers)
eda['distance_log'] = np.log1p(eda['distance_from_home_km'])

fig2 = px.box(
    eda.dropna(subset=['distance_log']),
    x='Fraud', y='distance_log',
    color='Fraud',
    color_discrete_map={'Legit': '#1f77b4', 'Fraud': '#d62728'},
    title='Distance from Home by Fraud Label (log scale)',
    labels={'distance_log': 'log(Distance from Home + 1 km)', 'Fraud': ''},
    points='outliers',
    template='plotly_white'
)
fig2.show()

# 3. Grouped Bar — Weekend vs Weekday fraud rate (normalised to % within each day type)
weekend_grp = (
    eda.dropna(subset=['is_weekend'])
       .groupby(['is_weekend', 'Fraud'])
       .size().reset_index(name='count')
)
weekend_grp['is_weekend'] = weekend_grp['is_weekend'].map({0.0: 'Weekday', 1.0: 'Weekend'})
totals = weekend_grp.groupby('is_weekend')['count'].transform('sum')
weekend_grp['pct'] = (weekend_grp['count'] / totals * 100).round(2)

fig3 = px.bar(
    weekend_grp, x='is_weekend', y='pct', color='Fraud',
    barmode='group',
    color_discrete_map={'Legit': '#1f77b4', 'Fraud': '#d62728'},
    title='Fraud vs Legitimate Transactions: Weekday vs Weekend (% of total)',
    labels={'is_weekend': '', 'pct': '% of Transactions'},
    text='pct',
    template='plotly_white'
)
fig3.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
fig3.update_layout(yaxis_ticksuffix='%')
fig3.show()

# 4. Box — Failed Auth Attempts by Fraud label
fig4 = px.box(
    eda.dropna(subset=['failed_auth_attempts']),
    x='Fraud', y='failed_auth_attempts',
    color='Fraud',
    color_discrete_map={'Legit': '#1f77b4', 'Fraud': '#d62728'},
    title='Failed Authentication Attempts by Fraud Label',
    labels={'failed_auth_attempts': 'Failed Auth Attempts', 'Fraud': ''},
    points='outliers',
    template='plotly_white'
)
fig4.show()

# ── Log-Transform Skewed Features ────────────────────────────────────────────
# These features are right-skewed (confirmed in EDA). log1p(x) = log(x+1)
# handles zeros safely and pulls extreme outliers toward the centre.
# Applied to adjusted_df BEFORE splitting so train and test get the same transform.
# StandardScaler inside the LR pipeline then centres and scales the result.

import numpy as np

# ── Log-Transform Skewed Features ─────────────────────────────────────────────
# Applied to X_train and X_test separately AFTER the split.
# log1p is deterministic (no fitting) so applying it to both sets independently
# is correct — no leakage risk.
# StandardScaler inside the LR pipeline then centres and scales the result.

skewed_cols = [
    'transaction_amount',
    'distance_from_home_km',
    'velocity_last_1hr',
    'account_age_days',
]
# amount_deviation_ratio excluded — legitimately negative, log1p would produce NaN

for col in skewed_cols:
    # Clip negatives introduced by MICE before log1p (log1p undefined for x < -1)
    X_train[col] = np.log1p(X_train[col].clip(lower=0))
    X_test[col]  = np.log1p(X_test[col].clip(lower=0))

print("Log-transform applied to X_train and X_test.")
print("\nNaN check — X_train:")
print(X_train[skewed_cols].isna().sum())
print("\nNaN check — X_test:")
print(X_test[skewed_cols].isna().sum())

# ── Train / Test Split ────────────────────────────────────────────────────────
X = adjusted_df.drop(columns=['is_fraudulent_transaction'])
y = adjusted_df['is_fraudulent_transaction']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

print(f"Train size: {X_train.shape}, Test size: {X_test.shape}")
print(f"Fraud rate — Train: {y_train.mean():.2%}, Test: {y_test.mean():.2%}")

# ── Bayesian Search with SMOTE inside Pipeline ────────────────────────────────
# StandardScaler placed after SMOTE so synthetic samples are also scaled
# SMOTE inside pipeline prevents leakage across CV folds

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

search_configs = [
    (
        'LogisticRegression',
        Pipeline([
            ('smote',  SMOTE(random_state=42)),
            ('scaler', StandardScaler()),
            ('model',  LogisticRegression(max_iter=1000, random_state=42))
        ]),
        {
            'model__C': Real(0.01, 10, prior='log-uniform'),
            'model__class_weight': Categorical(['balanced', None])
        }
    ),
    (
        'RandomForest',
        Pipeline([
            ('smote', SMOTE(random_state=42)),
            ('model', RandomForestClassifier(random_state=42))
        ]),
        {
            'model__n_estimators': Integer(50, 500),
            'model__max_depth': Integer(3, 20),
            'model__min_samples_split': Integer(2, 20),
            'model__class_weight': Categorical(['balanced', None])
        }
    ),
    (
        'XGBoost',
        Pipeline([
            ('smote', SMOTE(random_state=42)),
            ('model', XGBClassifier(eval_metric='logloss', random_state=42))
        ]),
        {
            'model__n_estimators': Integer(50, 500),
            'model__max_depth': Integer(3, 10),
            'model__learning_rate': Real(0.01, 0.3, prior='log-uniform'),
            'model__subsample': Real(0.5, 1.0),
            'model__scale_pos_weight': Integer(1, 20)
        }
    ),
]

results = []

for name, pipeline, space in search_configs:
    print(f"\nRunning Bayesian search for {name}...")
    search = BayesSearchCV(
        estimator=pipeline,
        search_spaces=space,
        n_iter=30,
        scoring='roc_auc',
        cv=cv,
        n_jobs=1,
        random_state=42,
        verbose=0
    )
    search.fit(X_train, y_train)
    results.append({
        'model': name,
        'best_score': search.best_score_,
        'best_params': search.best_params_,
        'fitted_search': search
    })
    print(f"{name} — CV AUC: {search.best_score_:.4f}")

# ── Evaluate Every Model + Feature Importance ─────────────────────────────────
def plot_feature_importance(name, model_step, feature_names):
    if hasattr(model_step, 'coef_'):
        importances = np.abs(model_step.coef_[0])
    elif hasattr(model_step, 'feature_importances_'):
        importances = model_step.feature_importances_
    else:
        print(f"  Feature importance not available for {name}")
        return

    feat_df = pd.DataFrame({
        'feature': feature_names,
        'importance': importances
    }).sort_values('importance', ascending=True).tail(20)

    fig = go.Figure(go.Bar(
        x=feat_df['importance'],
        y=feat_df['feature'],
        orientation='h',
        marker_color='steelblue'
    ))
    fig.update_layout(
        title=f'{name} — Top 20 Feature Importances',
        xaxis_title='Importance',
        yaxis_title='Feature',
        height=600,
        template='plotly_white'
    )
    fig.show()


for result in results:
    name       = result['model']
    best_est   = result['fitted_search'].best_estimator_
    y_pred     = best_est.predict(X_test)
    y_proba    = best_est.predict_proba(X_test)[:, 1]
    model_step = best_est.named_steps['model']

    print(f"\n{'='*55}")
    print(f"  {name}")
    print(f"  CV AUC:  {result['best_score']:.4f}")
    print(f"  ROC-AUC: {roc_auc_score(y_test, y_proba):.4f}")
    print(f"  PR-AUC:  {average_precision_score(y_test, y_proba):.4f}")
    print(f"{'='*55}")
    print(classification_report(y_test, y_pred, target_names=['Legit', 'Fraud']))
    plot_feature_importance(name, model_step, X_train.columns.tolist())

# ── Summary Table ─────────────────────────────────────────────────────────────
summary = pd.DataFrame([{
    'Model':   r['model'],
    'CV AUC':  round(r['best_score'], 4),
    'ROC-AUC': round(roc_auc_score(y_test, r['fitted_search'].best_estimator_.predict_proba(X_test)[:, 1]), 4),
    'PR-AUC':  round(average_precision_score(y_test, r['fitted_search'].best_estimator_.predict_proba(X_test)[:, 1]), 4),
} for r in results])

print("\nModel Comparison Summary:")
print(summary.sort_values('PR-AUC', ascending=False).to_string(index=False))

# ── Save Logistic Regression Model ───────────────────────────────────────────
lr_result   = next(r for r in results if r['model'] == 'LogisticRegression')
lr_pipeline = lr_result['fitted_search'].best_estimator_

joblib.dump(lr_pipeline, 'fraud_lr_model.pkl')
joblib.dump(X_train.columns.tolist(), 'model_features.pkl')
print("Model saved: fraud_lr_model.pkl")
print("Features saved: model_features.pkl")

# ── Threshold Tuning (Logistic Regression) ────────────────────────────────────
y_proba_lr = lr_pipeline.predict_proba(X_test)[:, 1]

precisions, recalls, thresholds = precision_recall_curve(y_test, y_proba_lr)
f1_scores      = 2 * (precisions * recalls) / (precisions + recalls + 1e-9)
best_idx       = f1_scores.argmax()
best_threshold = thresholds[best_idx]

print(f"\nOptimal threshold: {best_threshold:.4f}")
print(f"Precision: {precisions[best_idx]:.3f}  Recall: {recalls[best_idx]:.3f}  F1: {f1_scores[best_idx]:.3f}")

y_pred_tuned = (y_proba_lr >= best_threshold).astype(int)
print("\nClassification Report (tuned threshold):")
print(classification_report(y_test, y_pred_tuned, target_names=['Legit', 'Fraud']))

fig_pr = go.Figure()
fig_pr.add_trace(go.Scatter(x=recalls, y=precisions, mode='lines',
                             name='PR Curve', line=dict(color='steelblue', width=2)))
fig_pr.add_trace(go.Scatter(x=[recalls[best_idx]], y=[precisions[best_idx]],
                             mode='markers', name=f'Optimal threshold ({best_threshold:.2f})',
                             marker=dict(color='red', size=10)))
fig_pr.update_layout(title='Precision-Recall Curve — Logistic Regression',
                     xaxis_title='Recall', yaxis_title='Precision', template='plotly_white')
fig_pr.show()

joblib.dump(best_threshold, 'model_threshold.pkl')
print(f"Threshold saved: model_threshold.pkl")

# ── SHAP Values (Logistic Regression) ────────────────────────────────────────
scaler        = lr_pipeline.named_steps['scaler']
model_step    = lr_pipeline.named_steps['model']
X_test_scaled = scaler.transform(X_test)

explainer   = shap.LinearExplainer(model_step, X_test_scaled)
shap_values = explainer.shap_values(X_test_scaled)

# Global summary — which features drive fraud predictions across all transactions
shap.summary_plot(shap_values, X_test, feature_names=X_test.columns.tolist(), show=True)

# Waterfall — explain a single fraud transaction (first fraud case in test set)
fraud_idx = y_test[y_test == 1].index[0]
fraud_pos = X_test.index.get_loc(fraud_idx)
shap.waterfall_plot(shap.Explanation(
    values=shap_values[fraud_pos],
    base_values=explainer.expected_value,
    data=X_test.iloc[fraud_pos].values,
    feature_names=X_test.columns.tolist()
))
