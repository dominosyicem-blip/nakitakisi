#!/usr/bin/env python3
# Nakit - Aktif/Pasif Uygulaması (Tkinter) with SQLite + autosave + UNDO (Ctrl+Z)
# Full-featured version with APP_DIR support for onefile EXE deployments.
# This is your original (long) app logic with only the onefile-safe APP_DIR/DB path changes merged in.

import os
import sys
import signal
import traceback
from datetime import date, datetime

import sqlite3
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import db as db_helper  # local db helper (db.py)

# --- APP_DIR / data file locations (onefile-safe) ---
if getattr(sys, "frozen", False):
    # running as onefile executable -> store app data in %LOCALAPPDATA%\CashApp (Windows)
    appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    APP_DIR = os.path.join(appdata, "CashApp")
else:
    # running from source -> keep files next to script
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(APP_DIR, exist_ok=True)

DB_FILE = os.path.join(APP_DIR, "data.db")
AUTOSAVE_FILE = os.path.join(APP_DIR, "autosave.csv")

# --- Constants & columns ---
COLUMNS = ["id", "date", "group", "description", "amount"]
UNDO_STACK_MAX = 100

# --- Helpers ---
def format_amount_display(value, decimals=2):
    try:
        v = float(value)
    except Exception:
        return str(value)
    s = f"{v:,.{decimals}f}"
    s = s.replace(",", "_TMP_").replace(".", ",").replace("_TMP_", ".")
    return s

def parse_amount_input(s):
    s = str(s).strip()
    if s == "":
        raise ValueError("Boş tutar")
    sign = -1 if s.startswith("-") else 1
    if s[0] in "+-":
        s_body = s[1:].strip()
    else:
        s_body = s
    if "." in s_body and "," in s_body:
        s_body = s_body.replace(".", "")
        s_body = s_body.replace(",", ".")
    elif "," in s_body and "." not in s_body:
        s_body = s_body.replace(",", ".")
    elif "." in s_body and "," not in s_body:
        parts = s_body.split(".")
        if len(parts) > 2:
            s_body = "".join(parts)
        else:
            integer_part, frac_part = parts[0], parts[1]
            if len(frac_part) == 3 and len(integer_part) <= 3:
                s_body = integer_part + frac_part
            else:
                pass
    s_body = s_body.replace(" ", "")
    s_body = s_body.replace("'", "")
    try:
        val = float(s_body)
    except Exception:
        raise ValueError(f"Geçersiz tutar formatı: '{s}'")
    return sign * val

# --- Main application class ---
class CashApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nakit - Aktif/Pasif Uygulaması (SQLite)")

        # DB connection (uses DB_FILE)
        self.db_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        db_helper.init_db(self.db_conn)

        # DataFrame
        self.df = pd.DataFrame(columns=COLUMNS)
        self.load_db_into_df()

        # sort state and custom group order
        self.sort_state = {"col": None, "asc": True}
        self.group_order = ["Gelir", "Gider", "Aktif", "Pasif"]

        # undo stack
        self.undo_stack = []

        self.create_widgets()
        self.update_summary_and_view()

    def load_db_into_df(self):
        rows = db_helper.get_all(self.db_conn)
        if not rows:
            self.df = pd.DataFrame(columns=COLUMNS)
        else:
            self.df = pd.DataFrame(rows, columns=COLUMNS)
            self.df['amount'] = self.df['amount'].astype(float)
            self.df['id'] = self.df['id'].astype(int)

    def create_widgets(self):
        frm_top = ttk.Frame(self.root, padding=8)
        frm_top.pack(side="top", fill="x")

        ttk.Label(frm_top, text="Tarih (YYYY-MM-DD):").grid(row=0, column=0, sticky="w")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(frm_top, textvariable=self.date_var, width=12).grid(row=0, column=1, padx=4, pady=2)

        ttk.Label(frm_top, text="Grup:").grid(row=0, column=2, sticky="w")
        self.group_var = tk.StringVar(value="Gider")
        group_cb = ttk.Combobox(frm_top, textvariable=self.group_var, state="readonly", width=12)
        group_cb['values'] = ("Gelir", "Gider", "Aktif", "Pasif")
        group_cb.grid(row=0, column=3, padx=4, pady=2)

        ttk.Label(frm_top, text="Açıklama:").grid(row=0, column=4, sticky="w")
        self.desc_var = tk.StringVar()
        ttk.Entry(frm_top, textvariable=self.desc_var, width=30).grid(row=0, column=5, padx=4, pady=2)

        ttk.Label(frm_top, text="Tutar (manuel):").grid(row=0, column=6, sticky="w")
        self.amount_var = tk.StringVar()
        self.amount_entry = ttk.Entry(frm_top, textvariable=self.amount_var, width=18)
        self.amount_entry.grid(row=0, column=7, padx=4, pady=2)

        ttk.Button(frm_top, text="Ekle", command=self.add_item).grid(row=0, column=8, padx=6)
        ttk.Button(frm_top, text="Metin'e Aktar", command=self.export_text).grid(row=0, column=9, padx=6)
        ttk.Button(frm_top, text="Örnek Yükle", command=self.load_sample).grid(row=0, column=10, padx=6)

        frm_main = ttk.Frame(self.root, padding=6)
        frm_main.pack(side="top", fill="both", expand=True)

        tree_frame = ttk.Frame(frm_main)
        tree_frame.pack(side="left", fill="both", expand=True)

        cols = ("date", "group", "description", "amount", "percent")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("date", text="Tarih", command=lambda c="date": self.sort_by_column(c))
        self.tree.heading("group", text="Grup", command=lambda c="group": self.sort_by_column(c))
        self.tree.heading("description", text="Açıklama", command=lambda c="description": self.sort_by_column(c))
        self.tree.heading("amount", text="Tutar", command=lambda c="amount": self.sort_by_column(c))
        self.tree.heading("percent", text="Yüzde", command=lambda c="percent": self.sort_by_column(c))

        self.tree.column("date", width=100, anchor="center")
        self.tree.column("group", width=80, anchor="center")
        self.tree.column("description", width=220)
        self.tree.column("amount", width=140, anchor="e")
        self.tree.column("percent", width=100, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        right_frame = ttk.Frame(frm_main, width=360)
        right_frame.pack(side="right", fill="y")

        summary_frame = ttk.LabelFrame(right_frame, text="Özet", padding=8)
        summary_frame.pack(side="top", fill="x", padx=6, pady=6)

        self.lbl_gelir = ttk.Label(summary_frame, text="Toplam Gelir: 0,00")
        self.lbl_gelir.pack(anchor="w", pady=2)
        self.lbl_gider = ttk.Label(summary_frame, text="Toplam Gider: 0,00")
        self.lbl_gider.pack(anchor="w", pady=2)
        self.lbl_cash = ttk.Label(summary_frame, text="Elime Kalan Nakit (Gelir + Gider): 0,00")
        self.lbl_cash.pack(anchor="w", pady=2)
        self.lbl_aktif = ttk.Label(summary_frame, text="Toplam Aktif: 0,00")
        self.lbl_aktif.pack(anchor="w", pady=2)
        self.lbl_pasif = ttk.Label(summary_frame, text="Toplam Pasif: 0,00")
        self.lbl_pasif.pack(anchor="w", pady=2)
        self.lbl_net = ttk.Label(summary_frame, text="Net (Aktif - Pasif): 0,00")
        self.lbl_net.pack(anchor="w", pady=4)

        chart_frame = ttk.LabelFrame(right_frame, text="Gider Dağılımı (Pasta)", padding=8)
        chart_frame.pack(side="top", fill="both", expand=True, padx=6, pady=6)

        self.fig = Figure(figsize=(4,3), tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Hazır")
        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        status.pack(side="bottom", fill="x")

        # Bind Delete key to remove_selected
        self.root.bind('<Delete>', self.remove_selected)
        self.root.bind('<Control-Delete>', self.remove_selected)
        # Bind Ctrl+Z for undo
        self.root.bind_all('<Control-z>', self.undo)
        self.root.bind_all('<Control-Z>', self.undo)

    # --- Undo stack helpers ---
    def _push_undo(self, action: dict):
        """Push action to undo stack, cap size."""
        self.undo_stack.append(action)
        if len(self.undo_stack) > UNDO_STACK_MAX:
            self.undo_stack.pop(0)

    def undo(self, event=None):
        """Perform undo of last action (add or delete)."""
        try:
            if not self.undo_stack:
                messagebox.showinfo("Geri Al", "Geri alınacak işlem yok.")
                return "break"
            action = self.undo_stack.pop()
            typ = action.get('action')
            if typ == 'add':
                rid = action.get('id')
                if rid is None:
                    messagebox.showerror("Geri Al Hatası", "Geri alınacak işlem id bilgisi yok.")
                    return "break"
                try:
                    db_helper.delete_ids(self.db_conn, [rid])
                except Exception as e:
                    print("Undo delete error:", e)
                self.df = self.df[~(self.df['id'] == int(rid))].reset_index(drop=True)
                if self.sort_state["col"]:
                    self.sort_by_column(self.sort_state["col"])
                else:
                    self.update_summary_and_view()
                self.save_autosave()
                self.status_var.set(f"Son ekleme geri alındı (id={rid}).")
            elif typ == 'delete':
                rows = action.get('rows', [])
                if not rows:
                    messagebox.showerror("Geri Al Hatası", "Geri alınacak satır bilgisi yok.")
                    return "break"
                cur = self.db_conn.cursor()
                reinserted = []
                for r in rows:
                    try:
                        cur.execute(
                            "INSERT INTO transactions (id, date, \"group\", description, amount) VALUES (?, ?, ?, ?, ?)",
                            (int(r['id']), r['date'], r['group'], r.get('description', ''), float(r['amount']))
                        )
                        reinserted.append(int(r['id']))
                    except sqlite3.IntegrityError:
                        try:
                            cur.execute(
                                "INSERT INTO transactions (date, \"group\", description, amount) VALUES (?, ?, ?, ?)",
                                (r['date'], r['group'], r.get('description', ''), float(r['amount']))
                            )
                            reinserted.append(cur.lastrowid)
                        except Exception as e:
                            print("Undo reinsertion failed:", e)
                    except Exception as e:
                        print("Undo reinsertion error:", e)
                self.db_conn.commit()
                self.load_db_into_df()
                if self.sort_state["col"]:
                    self.sort_by_column(self.sort_state["col"])
                else:
                    self.update_summary_and_view()
                self.save_autosave()
                self.status_var.set(f"Son silme işlemi geri alındı ({len(reinserted)} öğe).")
            else:
                messagebox.showinfo("Geri Al", "Bu işlem geri alınamıyor.")
            return "break"
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Geri Al Hatası", f"Hata: {e}\n\n{tb}")
            return "break"

    # --- Sorting ---
    def sort_by_column(self, col):
        try:
            if self.sort_state["col"] == col:
                asc = not self.sort_state["asc"]
            else:
                asc = True

            if col == "group":
                order_map = {k: i for i, k in enumerate(self.group_order)}
                self.df["_sort_key"] = self.df["group"].map(lambda x: order_map.get(x, 9999))
                self.df = self.df.sort_values(by="_sort_key", ascending=asc, kind="mergesort").drop(columns="_sort_key")
            elif col == "amount":
                self.df = self.df.sort_values(by="amount", ascending=asc, kind="mergesort")
            elif col == "date":
                def _parse(d):
                    try:
                        return datetime.fromisoformat(str(d))
                    except Exception:
                        try:
                            return datetime.strptime(str(d), "%d.%m.%Y")
                        except Exception:
                            return datetime.min
                self.df["_sort_key"] = self.df["date"].apply(_parse)
                self.df = self.df.sort_values(by="_sort_key", ascending=asc, kind="mergesort").drop(columns="_sort_key")
            elif col == "percent":
                total_gelir = self.df[self.df['group']=="Gelir"]['amount'].sum()
                total_gider = self.df[self.df['group']=="Gider"]['amount'].sum()
                total_aktif = self.df[self.df['group']=="Aktif"]['amount'].sum()
                total_pasif = self.df[self.df['group']=="Pasif"]['amount'].sum()
                abs_total_gelir = abs(total_gelir) if total_gelir != 0 else 0
                abs_total_gider = abs(total_gider) if total_gider != 0 else 0
                abs_total_aktif_pasif = (abs(total_aktif) + abs(total_pasif)) if (total_aktif != 0 or total_pasif != 0) else 0
                def _pct(row):
                    grp = row['group']
                    amt = row['amount']
                    if grp == "Gelir" and abs_total_gelir>0:
                        return (abs(amt) / abs_total_gelir) * 100
                    elif grp == "Gider" and abs_total_gider>0:
                        return (abs(amt) / abs_total_gider) * 100
                    elif grp in ("Aktif","Pasif") and abs_total_aktif_pasif>0:
                        return (abs(amt) / abs_total_aktif_pasif) * 100
                    return 0.0
                self.df["_sort_key"] = self.df.apply(_pct, axis=1)
                self.df = self.df.sort_values(by="_sort_key", ascending=asc, kind="mergesort").drop(columns="_sort_key")
            else:
                self.df = self.df.sort_values(by=col, key=lambda s: s.astype(str).str.lower(), ascending=asc, kind="mergesort")

            # Reset index after sort to keep DataFrame clean
            self.df = self.df.reset_index(drop=True)
            self.sort_state = {"col": col, "asc": asc}
            self.update_summary_and_view()
            direction = "↑" if asc else "↓"
            self.status_var.set(f"Sıralandı: {col} {direction}")
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Sıralama Hatası", f"Sıralanırken hata: {e}\n\n{tb}")

    def parse_date(self, s):
        s = s.strip()
        if not s:
            return date.today().isoformat()
        try:
            dt = datetime.fromisoformat(s)
            return dt.date().isoformat()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.date().isoformat()
            except Exception:
                continue
        return s

    def add_item(self):
        try:
            date_text = self.parse_date(self.date_var.get())
            grp = self.group_var.get()
            desc = self.desc_var.get().strip()
            amt_text = self.amount_var.get().strip()
            if not amt_text:
                messagebox.showwarning("Eksik", "Lütfen tutar girin.")
                return
            try:
                raw_amt = parse_amount_input(amt_text)
            except ValueError as e:
                messagebox.showerror("Hata", str(e))
                return

            mag = abs(raw_amt)
            if grp in ("Gider", "Pasif"):
                amt_signed = -mag
            else:
                amt_signed = mag

            # insert into DB and get id
            new_id = db_helper.insert(self.db_conn, date_text, grp, desc, float(amt_signed))
            # append to DataFrame
            new_row = {"id": int(new_id), "date": date_text, "group": grp, "description": desc, "amount": float(amt_signed)}
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
            # push undo action for add
            self._push_undo({'action': 'add', 'id': int(new_id)})
            # clear inputs
            self.desc_var.set("")
            self.amount_var.set("")
            # re-apply sort if needed
            if self.sort_state["col"]:
                self.sort_by_column(self.sort_state["col"])
            else:
                self.update_summary_and_view()
            # autosave CSV backup
            self.save_autosave()
            sign = "+" if amt_signed >= 0 else "-"
            self.status_var.set(f"'{desc}' eklendi -> {grp} {sign}{format_amount_display(abs(amt_signed))}")
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Beklenmeyen Hata", f"Hata oluştu:\n{e}\n\n{tb}")

    def remove_selected(self, event=None):
        try:
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo("Seçim Yok", "Lütfen silmek için bir veya daha fazla satır seçin.")
                return
            ids = []
            for iid in sel:
                try:
                    ids.append(int(iid))
                except Exception:
                    messagebox.showerror("Hata", "Seçilen öğe ile ilgili bir hata oluştu (iid dönüşümü).")
                    return
            if not ids:
                return
            if len(ids) == 1:
                confirm = messagebox.askyesno("Onay", "Seçili öğeyi silmek istiyor musunuz?")
            else:
                confirm = messagebox.askyesno("Onay", f"{len(ids)} seçili öğeyi silmek istiyor musunuz?")
            if not confirm:
                return
            # collect rows before deletion for undo
            rows = []
            for rid in ids:
                row = self.df[self.df['id'] == rid]
                if not row.empty:
                    r = row.iloc[0]
                    rows.append({'id': int(r['id']), 'date': r['date'], 'group': r['group'], 'description': r['description'], 'amount': float(r['amount'])})
            # delete from DB
            db_helper.delete_ids(self.db_conn, ids)
            # remove from df
            self.df = self.df[~self.df['id'].isin(ids)].reset_index(drop=True)
            # push undo action for delete (store rows)
            if rows:
                self._push_undo({'action': 'delete', 'rows': rows})
            # re-apply sort or update
            if self.sort_state["col"]:
                self.sort_by_column(self.sort_state["col"])
            else:
                self.update_summary_and_view()
            # autosave
            self.save_autosave()
            self.status_var.set(f"{len(ids)} öğe silindi.")
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Beklenmeyen Hata", f"Hata oluştu:\n{e}\n\n{tb}")

    def export_text(self):
        try:
            if self.df.empty:
                messagebox.showinfo("Boş", "Dışa aktarılacak veri yok.")
                return
            file = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Metin dosyası","*.txt")])
            if not file:
                return

            total_gelir = self.df[self.df['group']=="Gelir"]['amount'].sum()
            total_gider = self.df[self.df['group']=="Gider"]['amount'].sum()
            total_aktif = self.df[self.df['group']=="Aktif"]['amount'].sum()
            total_pasif = self.df[self.df['group']=="Pasif"]['amount'].sum()
            net_assets = total_aktif + total_pasif
            cash_on_hand = total_gelir + total_gider

            abs_total_gelir = abs(total_gelir) if total_gelir != 0 else 0
            abs_total_gider = abs(total_gider) if total_gider != 0 else 0
            abs_total_aktif_pasif = (abs(total_aktif) + abs(total_pasif)) if (total_aktif != 0 or total_pasif != 0) else 0

            def parse_for_sort(d):
                try:
                    return datetime.fromisoformat(d)
                except Exception:
                    try:
                        return datetime.strptime(d, "%d.%m.%Y")
                    except Exception:
                        return datetime.min

            df_sorted = self.df.copy()
            try:
                df_sorted['__sort'] = df_sorted['date'].apply(parse_for_sort)
                df_sorted = df_sorted.sort_values('__sort').drop(columns='__sort')
            except Exception:
                pass

            lines = []
            lines.append("Nakit Kayıtları\n")
            lines.append("Tarih | Grup | Açıklama | Tutar | Grup içi %\n")
            for idx, row in df_sorted.reset_index().iterrows():
                grp = row['group']
                desc = row['description']
                dt = str(row['date'])
                amt = row['amount']
                pct = 0.0
                if grp == "Gelir" and abs_total_gelir>0:
                    pct = (abs(amt) / abs_total_gelir) * 100
                elif grp == "Gider" and abs_total_gider>0:
                    pct = (abs(amt) / abs_total_gider) * 100
                elif grp in ("Aktif","Pasif") and abs_total_aktif_pasif>0:
                    pct = (abs(amt) / abs_total_aktif_pasif) * 100
                lines.append(f"{dt} | {grp} | {desc} | {format_amount_display(amt)} | {pct:.1f}%")

            lines.append("\nGenel Toplamlar\n")
            lines.append(f"Toplam Gelir: {format_amount_display(total_gelir)}")
            lines.append(f"Toplam Gider: {format_amount_display(total_gider)}")
            lines.append(f"Elime Kalan Nakit (Gelir + Gider): {format_amount_display(cash_on_hand)}")
            lines.append(f"Toplam Aktif: {format_amount_display(total_aktif)}")
            lines.append(f"Toplam Pasif: {format_amount_display(total_pasif)}")
            lines.append(f"Net (Aktif - Pasif): {format_amount_display(net_assets)}")

            lines.append("\nGider Dağılımı (Açıklama bazında)\n")
            gasto = self.df[self.df['group']=="Gider"]
            if gasto.empty:
                lines.append("Gider yok.")
            else:
                g = gasto.groupby('description')['amount'].sum()
                total_g = abs(g.sum())
                g = g.abs().sort_values(ascending=False)
                for desc, amt_abs in g.items():
                    pct = (amt_abs / total_g) * 100 if total_g > 0 else 0
                    lbl = desc if desc else "Diğer"
                    lines.append(f"{lbl}: {format_amount_display(amt_abs)} ({pct:.1f}%)")

            with open(file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            messagebox.showinfo("Tamam", f"Metin dosyasına aktarıldı: {file}")
            self.status_var.set(f"Metin dosyasına aktarıldı: {file}")
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Metin dosyasına aktarma başarısız", f"{e}\n\n{tb}")

    def load_sample(self):
        try:
            sample = [
                {"date": "2025-01-05", "group":"Gelir", "description":"Satış", "amount":5000},
                {"date": "2025-01-20", "group":"Gider", "description":"Kira", "amount":1200},
                {"date": "2025-02-10", "group":"Gider", "description":"Tedarik", "amount":1800},
                {"date": "2025-02-15", "group":"Gelir", "description":"Hizmet", "amount":3000},
                {"date": "2025-03-01", "group":"Aktif", "description":"Bina", "amount":25000},
                {"date": "2025-03-15", "group":"Pasif", "description":"Kredi", "amount":10000},
            ]
            # clear DB then insert
            db_helper.clear_all(self.db_conn)
            for r in sample:
                mag = abs(r["amount"])
                amt = -mag if r["group"] in ("Gider", "Pasif") else mag
                db_helper.insert(self.db_conn, r["date"], r["group"], r["description"], float(amt))
            # reload df from DB
            self.load_db_into_df()
            # clear undo stack because this is a bulk replace
            self.undo_stack.clear()
            if self.sort_state["col"]:
                self.sort_by_column(self.sort_state["col"])
            else:
                self.update_summary_and_view()
            # autosave CSV backup
            self.save_autosave()
            self.status_var.set("Örnek veri yüklendi.")
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Hata", f"Örnek yüklenirken hata: {e}\n\n{tb}")

    def update_summary_and_view(self):
        try:
            total_gelir = self.df[self.df['group']=="Gelir"]['amount'].sum() if not self.df.empty else 0.0
            total_gider = self.df[self.df['group']=="Gider"]['amount'].sum() if not self.df.empty else 0.0
            total_aktif = self.df[self.df['group']=="Aktif"]['amount'].sum() if not self.df.empty else 0.0
            total_pasif = self.df[self.df['group']=="Pasif"]['amount'].sum() if not self.df.empty else 0.0
            net_assets = total_aktif + total_pasif
            cash_on_hand = total_gelir + total_gider

            self.lbl_gelir.config(text=f"Toplam Gelir: {format_amount_display(total_gelir)}")
            self.lbl_gider.config(text=f"Toplam Gider: {format_amount_display(total_gider)}")
            self.lbl_cash.config(text=f"Elime Kalan Nakit (Gelir + Gider): {format_amount_display(cash_on_hand)}")
            self.lbl_aktif.config(text=f"Toplam Aktif: {format_amount_display(total_aktif)}")
            self.lbl_pasif.config(text=f"Toplam Pasif: {format_amount_display(total_pasif)}")
            self.lbl_net.config(text=f"Net (Aktif - Pasif): {format_amount_display(net_assets)}")

            # rebuild tree using DB ids as iid
            for i in self.tree.get_children():
                self.tree.delete(i)

            abs_total_gelir = abs(total_gelir) if total_gelir != 0 else 0
            abs_total_gider = abs(total_gider) if total_gider != 0 else 0
            abs_total_aktif_pasif = (abs(total_aktif) + abs(total_pasif)) if (total_aktif != 0 or total_pasif != 0) else 0

            for _, row in self.df.iterrows():
                rid = int(row['id'])
                dt = row['date']
                grp = row['group']
                desc = row['description']
                amt = float(row['amount'])
                pct = 0.0
                if grp == "Gelir" and abs_total_gelir>0:
                    pct = (abs(amt) / abs_total_gelir) * 100
                elif grp == "Gider" and abs_total_gider>0:
                    pct = (abs(amt) / abs_total_gider) * 100
                elif grp in ("Aktif","Pasif") and abs_total_aktif_pasif>0:
                    pct = (abs(amt) / abs_total_aktif_pasif) * 100
                pct_text = f"{pct:.1f}%"
                amt_display = format_amount_display(amt)
                self.tree.insert("", "end", iid=str(rid), values=(dt, grp, desc, amt_display, pct_text))

            self.update_chart()
        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Hata", f"Görünüm güncellenirken hata: {e}\n\n{tb}")

    def update_chart(self):
        try:
            self.ax.clear()
            gasto = self.df[self.df['group']=="Gider"]
            if gasto.empty:
                self.ax.text(0.5,0.5, "Gider yok", ha="center", va="center")
            else:
                g = gasto.groupby('description')['amount'].sum()
                labels = g.index.tolist()
                sizes = [abs(v) for v in g.values.tolist()]
                labels = [lbl if lbl else "Diğer" for lbl in labels]
                self.ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
                self.ax.axis('equal')
                self.ax.set_title("Gider Dağılımı")
            self.canvas.draw_idle()
        except Exception:
            tb = traceback.format_exc()
            self.ax.clear()
            self.ax.text(0.5,0.5, "Grafik oluşturulamadı", ha="center", va="center")
            self.canvas.draw_idle()
            print("Grafik hatası:", tb)

    # autosave CSV backup
    def save_autosave(self, filename=AUTOSAVE_FILE):
        try:
            if not self.df.empty:
                # include id for reference
                self.df.to_csv(filename, index=False)
            else:
                # if empty, remove previous autosave to avoid stale recovery
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except:
                        pass
        except Exception:
            pass

    def save_autosave_and_quit(self, sig=None, frame=None):
        try:
            self.save_autosave()
            self.status_var.set(f"Autosave oluşturuldu: {AUTOSAVE_FILE}")
        except Exception:
            pass
        try:
            # close DB connection gracefully
            try:
                self.db_conn.close()
            except:
                pass
            self.root.quit()
        except Exception:
            pass

# --- main ---
def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use('clam')
    except:
        pass

    app = CashApp(root)

    # Capture SIGINT (Ctrl+C) for graceful autosave + quit
    try:
        signal.signal(signal.SIGINT, lambda s,f: app.save_autosave_and_quit(s,f))
    except Exception:
        pass

    # If DB empty and autosave exists, offer to import it
    try:
        db_rows = db_helper.get_all(app.db_conn)
        if not db_rows and os.path.exists(AUTOSAVE_FILE):
            if messagebox.askyesno("Kurtarma", f"Önceki bir oturumdan otomatik kaydetme bulundu ({AUTOSAVE_FILE}). DB boş. Yüklemek ister misiniz?"):
                try:
                    df_recovered = pd.read_csv(AUTOSAVE_FILE)
                    required = {"date","group","description","amount"}
                    if required.issubset(set(df_recovered.columns)):
                        for _, r in df_recovered.iterrows():
                            try:
                                dt = r['date']
                                grp = r['group']
                                desc = r['description']
                                amt = float(r['amount'])
                                db_helper.insert(app.db_conn, dt, grp, desc, amt)
                            except Exception:
                                pass
                        app.load_db_into_df()
                        app.update_summary_and_view()
                        app.status_var.set("Autosave veritabanına yüklendi.")
                    else:
                        messagebox.showwarning("Uyarı", "Autosave dosyası beklenen formatta değil.")
                except Exception as e:
                    messagebox.showerror("Hata", f"Autosave yüklenemedi: {e}")
    except Exception:
        pass

    try:
        root.geometry("1100x560")
        root.mainloop()
    except KeyboardInterrupt:
        try:
            app.save_autosave()
        except:
            pass
    finally:
        try:
            app.db_conn.close()
        except:
            pass

if __name__ == "__main__":
    main()