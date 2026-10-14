import csv, json, os, queue, subprocess, sys, threading, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from policy import SourcePolicyRegistry
from parser_factory import create_parser

APP_NAME = "EnergoStor Parser v0.5"
WORK_DIR = Path.cwd()
CONFIG_PATH = WORK_DIR / "config" / "sources.json"
DATA_DIR = WORK_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x780")
        self.minsize(980, 650)

        self.registry = SourcePolicyRegistry(CONFIG_PATH)
        self.domain_by_name = {
            self.registry.display_name(d): d for d in self.registry.domains()
        }

        self.msgq = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

        names = list(self.domain_by_name)
        self.source_var = tk.StringVar(value=names[0] if names else "")
        self.limit_var = tk.IntVar(value=20)
        self.status_var = tk.StringVar(value="Готов")
        self.progress_var = tk.DoubleVar(value=0)

        self.policy_vars = {}
        self._ui()
        self._refresh_policy_panel()
        self.after(100, self._poll)

    def _ui(self):
        pad = 14
        top = ttk.Frame(self, padding=pad)
        top.pack(fill="x")

        ttk.Label(top, text="EnergoStor Parser v0.5", font=("Segoe UI",18,"bold")).grid(row=0,column=0,columnspan=5,sticky="w")
        ttk.Label(top, text="Универсальный сборщик с политиками по источникам").grid(row=1,column=0,columnspan=5,sticky="w",pady=(2,14))

        ttk.Label(top, text="Источник").grid(row=2,column=0,sticky="w")
        self.source_box = ttk.Combobox(
            top, textvariable=self.source_var,
            values=list(self.domain_by_name), state="readonly", width=25
        )
        self.source_box.grid(row=3,column=0,sticky="ew",padx=(0,12))
        self.source_box.bind("<<ComboboxSelected>>", lambda e:self._refresh_policy_panel())

        ttk.Label(top, text="Лимит товаров").grid(row=2,column=1,sticky="w")
        ttk.Spinbox(top, from_=1, to=10000, textvariable=self.limit_var, width=14).grid(row=3,column=1,sticky="w",padx=(0,12))

        self.start_btn = ttk.Button(top, text="НАЧАТЬ ПАРСИНГ", command=self.start)
        self.start_btn.grid(row=3,column=2,sticky="ew",padx=(0,8))
        self.stop_btn = ttk.Button(top, text="СТОП", command=self.stop, state="disabled")
        self.stop_btn.grid(row=3,column=3,sticky="ew",padx=(0,8))
        ttk.Button(top, text="Открыть sources.json", command=lambda:self.open_file(CONFIG_PATH)).grid(row=3,column=4,sticky="ew")

        for c in range(5):
            top.columnconfigure(c, weight=1 if c in (0,2,3,4) else 0)

        # Policy panel
        self.policy_frame = ttk.LabelFrame(self, text="Политика источника", padding=10)
        self.policy_frame.pack(fill="x", padx=pad, pady=(0,10))

        policy_keys = [
            ("parse_images","Изображения"),
            ("parse_documents","Документы"),
            ("parse_description","Описание"),
            ("parse_price","Цена"),
            ("parse_attributes","Характеристики"),
            ("parse_manufacturer","Производитель"),
            ("parse_category","Категория"),
        ]
        for i,(key,label) in enumerate(policy_keys):
            v = tk.BooleanVar()
            self.policy_vars[key] = v
            cb = ttk.Checkbutton(self.policy_frame, text=label, variable=v)
            cb.grid(row=0,column=i,sticky="w",padx=(0,18))

        self.save_policy_btn = ttk.Button(
            self.policy_frame,
            text="СОХРАНИТЬ ПОЛИТИКУ",
            command=self._save_policy
        )
        self.save_policy_btn.grid(row=0, column=len(policy_keys), sticky="e", padx=(12,0))

        self.policy_info = ttk.Label(self.policy_frame, text="")
        self.policy_info.grid(row=1,column=0,columnspan=len(policy_keys)+1,sticky="w",pady=(8,0))

        mid = ttk.Frame(self, padding=(pad,0,pad,8))
        mid.pack(fill="x")
        ttk.Progressbar(mid, variable=self.progress_var, maximum=100).pack(fill="x")
        ttk.Label(mid, textvariable=self.status_var).pack(anchor="w", pady=(6,0))

        table_frame = ttk.LabelFrame(self, text="Товары", padding=8)
        table_frame.pack(fill="both", expand=False, padx=pad, pady=(0,8))

        cols = ("source","manufacturer","model","category","attrs","docs","images","quality")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=11)
        headers = {
            "source":"Источник","manufacturer":"Производитель","model":"Модель / артикул",
            "category":"Категория","attrs":"Характ.","docs":"Док.","images":"Фото","quality":"Качество"
        }
        widths = {"source":100,"manufacturer":130,"model":180,"category":300,"attrs":75,"docs":65,"images":55,"quality":90}
        for c in cols:
            self.tree.heading(c,text=headers[c])
            self.tree.column(c,width=widths[c],anchor="w" if c in ("source","manufacturer","model","category") else "center")
        self.tree.pack(fill="both", expand=True)

        lf = ttk.LabelFrame(self, text="Журнал", padding=8)
        lf.pack(fill="both", expand=True, padx=pad, pady=(0,pad))
        self.logbox = tk.Text(lf, wrap="word", font=("Consolas",9), state="disabled")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bottom = ttk.Frame(self, padding=(pad,0,pad,pad))
        bottom.pack(fill="x")
        ttk.Button(bottom,text="Открыть CSV",command=lambda:self.open_file(DATA_DIR/"products.csv")).pack(side="left")
        ttk.Button(bottom,text="Открыть JSON",command=lambda:self.open_file(DATA_DIR/"products.json")).pack(side="left",padx=8)
        ttk.Button(bottom,text="Открыть папку",command=lambda:self.open_file(DATA_DIR)).pack(side="left")

    def _selected_domain(self):
        return self.domain_by_name[self.source_var.get()]

    def _refresh_policy_panel(self):
        if not self.source_var.get():
            return
        domain = self._selected_domain()
        p = self.registry.get(domain)
        for key,var in self.policy_vars.items():
            var.set(bool(p.get(key, False)))
        self.policy_info.config(
            text=f"{domain}  |  delay={p.get('rate_limit_seconds',1.5)} сек  |  parser={p.get('parser','')}"
        )

    def _save_policy(self):
        domain = self._selected_domain()
        flags = {key: var.get() for key, var in self.policy_vars.items()}

        # Extra confirmation for turning image collection ON.
        old = self.registry.get(domain)
        if flags.get("parse_images") and not old.get("parse_images", False):
            ok = messagebox.askyesno(
                APP_NAME,
                f"Включить сбор изображений для {domain}?\n\n"
                "Убедись, что изображения этого источника разрешено использовать."
            )
            if not ok:
                self.policy_vars["parse_images"].set(False)
                flags["parse_images"] = False

        self.registry.update_flags(domain, flags)
        self.registry.reload()
        self._refresh_policy_panel()
        messagebox.showinfo(APP_NAME, f"Политика {domain} сохранена.")

    def log(self, text):
        self.msgq.put(("log",text))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            limit = int(self.limit_var.get())
            if limit < 1:
                raise ValueError
        except Exception:
            messagebox.showerror(APP_NAME,"Некорректный лимит.")
            return

        self.registry.reload()
        domain = self._selected_domain()
        policy = self.registry.get(domain)
        if not policy.get("enabled", True):
            messagebox.showerror(APP_NAME,"Источник отключён в sources.json.")
            return

        max_run = int(policy.get("max_pages_per_run", limit))
        limit = min(limit, max_run)

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.stop_event.clear()
        self.progress_var.set(0)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        self.worker = threading.Thread(target=self._run,args=(domain,policy,limit),daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.log("Получена команда STOP")
        self.status_var.set("Останавливаю после текущего запроса...")

    def _run(self, domain, policy, limit):
        try:
            parser = create_parser(policy["parser"], policy)
            self.log(f"Источник: {domain}")
            self.log(
                "POLICY "
                f"images={policy.get('parse_images')} "
                f"documents={policy.get('parse_documents')} "
                f"description={policy.get('parse_description')} "
                f"price={policy.get('parse_price')} "
                f"attributes={policy.get('parse_attributes')}"
            )
            self.msgq.put(("status",f"Ищу карточки: {self.registry.display_name(domain)}..."))
            urls = parser.discover_urls(limit=limit,stop_event=self.stop_event,log=self.log)
            self.log(f"Найдено URL: {len(urls)}")
            if not urls:
                raise RuntimeError("Карточки не найдены.")

            products = []
            for i,url in enumerate(urls,1):
                if self.stop_event.is_set():
                    break
                self.msgq.put(("status",f"Обрабатываю {i}/{len(urls)}"))
                try:
                    p = parser.parse_url(url)
                    d = p.to_dict()
                    products.append(d)
                    self.log(
                        f"[{i}/{len(urls)}] OK {d['manufacturer']} {d['model']} "
                        f"| attrs={len(d['attributes'])} docs={len(d['documents'])} "
                        f"images={len(d['images'])} | {d['quality']}"
                    )
                    self.msgq.put(("row",d))
                except Exception as e:
                    self.log(f"[{i}/{len(urls)}] ERROR {url}: {e}")
                self.msgq.put(("progress",i/len(urls)*100))
                time.sleep(parser.delay)

            (DATA_DIR/"products.json").write_text(
                json.dumps(products,ensure_ascii=False,indent=2),encoding="utf-8"
            )

            fields = [
                "source","source_url","external_id","manufacturer","model","sku",
                "name","category","quality","dedupe_key","description","price",
                "attributes_json","documents_json","images_json"
            ]
            with (DATA_DIR/"products.csv").open("w",newline="",encoding="utf-8-sig") as f:
                w = csv.DictWriter(f,fieldnames=fields)
                w.writeheader()
                for p in products:
                    row = {k:p.get(k,"") for k in fields}
                    row["attributes_json"] = json.dumps(p.get("attributes",{}),ensure_ascii=False)
                    row["documents_json"] = json.dumps(p.get("documents",[]),ensure_ascii=False)
                    row["images_json"] = json.dumps(p.get("images",[]),ensure_ascii=False)
                    w.writerow(row)

            good = sum(p["quality"]=="GOOD" for p in products)
            normal = sum(p["quality"]=="NORMAL" for p in products)
            poor = sum(p["quality"]=="POOR" for p in products)
            self.log(f"DONE saved={len(products)} GOOD={good} NORMAL={normal} POOR={poor}")
            self.msgq.put(("status",f"Готово: {len(products)} | GOOD {good} | NORMAL {normal} | POOR {poor}"))
        except Exception as e:
            self.log(f"FATAL: {e}")
            self.msgq.put(("error",str(e)))
            self.msgq.put(("status","Ошибка"))
        finally:
            self.msgq.put(("done",None))

    def _poll(self):
        try:
            while True:
                kind,data = self.msgq.get_nowait()
                if kind == "log":
                    self.logbox.config(state="normal")
                    self.logbox.insert("end",data+"\n")
                    self.logbox.see("end")
                    self.logbox.config(state="disabled")
                elif kind == "status":
                    self.status_var.set(data)
                elif kind == "progress":
                    self.progress_var.set(data)
                elif kind == "row":
                    self.tree.insert("", "end", values=(
                        data["source"],data["manufacturer"],data["model"],data["category"],
                        len(data.get("attributes",{})),len(data.get("documents",[])),
                        len(data.get("images",[])),data["quality"]
                    ))
                elif kind == "error":
                    messagebox.showerror(APP_NAME,data)
                elif kind == "done":
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100,self._poll)

    def open_file(self,p):
        p = Path(p)
        if not p.exists():
            messagebox.showinfo(APP_NAME,f"Файл пока не создан:\n{p}")
            return
        if sys.platform.startswith("win"):
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open",str(p)])

if __name__ == "__main__":
    App().mainloop()
