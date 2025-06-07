# finance_app_streamlit.py
"""Simple personal finance tracker built with Streamlit + SQLite.

Run with:
    streamlit run finance_app_streamlit.py
The database file 'financas.db' is created in the same folder.
"""

import sqlite3
from contextlib import closing
from datetime import date, datetime

import pandas as pd
import streamlit as st

DB_PATH = "financas.db"


# ---------- persistence layer ----------
def get_conn():
    """Return a threaded‑safe SQLite connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                balance REAL DEFAULT 0
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                type TEXT CHECK(type IN ('Income','Expense','Transfer')) NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                account_id INTEGER,
                category_id INTEGER,
                description TEXT,
                amount REAL NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id),
                FOREIGN KEY(category_id) REFERENCES categories(id)
            );
            """
        )
        conn.commit()


@st.cache_data(show_spinner=False)
def get_df(query, params=()):
    """Utility to read a SQL query into a DataFrame."""
    with closing(get_conn()) as conn:
        return pd.read_sql_query(query, conn, params=params, parse_dates=["date"])


def execute_sql(stmt, params=()):
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute(stmt, params)
        conn.commit()
        return cur.lastrowid


# ---------- application logic ----------
def add_account():
    st.header("Nova conta")
    with st.form("add_account"):
        name = st.text_input("Nome da conta")
        balance = st.number_input("Saldo inicial (R$)", value=0.0, step=0.01, format="%.2f")
        submitted = st.form_submit_button("Salvar")
        if submitted and name:
            try:
                execute_sql(
                    "INSERT INTO accounts (name, balance) VALUES (?, ?)",
                    (name.strip(), balance),
                )
                st.success("Conta adicionada com sucesso!")
            except sqlite3.IntegrityError:
                st.error("Já existe uma conta com esse nome.")


def list_accounts():
    st.header("Contas")
    df = get_df("SELECT id, name, balance FROM accounts ORDER BY name")
    st.dataframe(df, use_container_width=True)


def add_category():
    st.header("Nova categoria")
    with st.form("add_cat"):
        name = st.text_input("Nome da categoria")
        type_ = st.selectbox("Tipo", ["Income", "Expense", "Transfer"])
        submitted = st.form_submit_button("Salvar")
        if submitted and name:
            try:
                execute_sql(
                    "INSERT INTO categories (name, type) VALUES (?,?)",
                    (name.strip(), type_),
                )
                st.success("Categoria adicionada!")
            except sqlite3.IntegrityError:
                st.error("Já existe uma categoria com esse nome.")


def list_categories():
    st.header("Categorias")
    df = get_df("SELECT id, name, type FROM categories ORDER BY type, name")
    st.dataframe(df, use_container_width=True)


def add_transaction():
    st.header("Novo lançamento")
    accounts = get_df("SELECT id, name FROM accounts")
    categories = get_df("SELECT id, name, type FROM categories")
    if accounts.empty or categories.empty:
        st.info("Cadastre ao menos uma conta e uma categoria primeiro.")
        return

    with st.form("add_tx"):
        col1, col2 = st.columns(2)
        date_tx = col1.date_input("Data", value=date.today())
        account_name = col2.selectbox("Conta", accounts["name"].tolist())
        category_name = st.selectbox("Categoria", categories["name"].tolist())
        description = st.text_input("Descrição (opcional)")
        amount = st.number_input("Valor (R$)", step=0.01, format="%.2f")
        if st.form_submit_button("Salvar"):
            acc_id = accounts.loc[accounts["name"] == account_name, "id"].iat[0]
            cat_id = categories.loc[categories["name"] == category_name, "id"].iat[0]
            execute_sql(
                "INSERT INTO transactions (date, account_id, category_id, description, amount) VALUES (?,?,?,?,?)",
                (date_tx.isoformat(), acc_id, cat_id, description, amount),
            )
            # update account balance
            execute_sql("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, acc_id))
            st.success("Lançamento registrado!")


def list_transactions():
    st.header("Lançamentos")
    query = """
        SELECT t.id,
               date,
               a.name AS account,
               c.name AS category,
               c.type AS type,
               description,
               amount
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        JOIN categories c ON c.id = t.category_id
        ORDER BY date DESC, t.id DESC
    """
    df = get_df(query)
    st.dataframe(df, use_container_width=True)


def reports():
    st.header("Relatórios")
    df_tx = get_df(
        """
        SELECT date,
               amount,
               c.type,
               c.name as category
        FROM transactions
        JOIN categories c ON c.id = category_id
        """
    )
    if df_tx.empty:
        st.info("Não há dados suficientes para exibir relatórios.")
        return

    # Fluxo de saldo acumulado
    df_tx_sorted = df_tx.sort_values("date")
    df_tx_sorted["saldo_acumulado"] = df_tx_sorted["amount"].cumsum()
    st.subheader("Saldo acumulado")
    st.line_chart(df_tx_sorted[["date", "saldo_acumulado"]].set_index("date"))

    # Gastos por categoria
    df_expense = (
        df_tx[df_tx["type"] == "Expense"]
        .groupby("category")["amount"]
        .sum()
        .abs()
        .sort_values(ascending=False)
    )
    if not df_expense.empty:
        st.subheader("Despesas por categoria (R$)")
        st.bar_chart(df_expense)

    # Receita versus despesa mensal
    df_tx["month"] = df_tx["date"].dt.to_period("M").dt.to_timestamp()
    df_month = df_tx.pivot_table(
        values="amount",
        index="month",
        columns="type",
        aggfunc="sum",
        fill_value=0,
    ).sort_index()
    st.subheader("Receita vs Despesa (mensal)")
    st.bar_chart(df_month)


# ---------- Streamlit layout ----------
st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide")
init_db()

PAGES = {
    "Lançamentos": list_transactions,
    "Adicionar lançamento": add_transaction,
    "Contas": list_accounts,
    "Adicionar conta": add_account,
    "Categorias": list_categories,
    "Adicionar categoria": add_category,
    "Relatórios": reports,
}

with st.sidebar:
    st.title("💰 Financeiro")
    selection = st.radio("Selecione uma página", list(PAGES.keys()))

# Render selected page
PAGES[selection]()
