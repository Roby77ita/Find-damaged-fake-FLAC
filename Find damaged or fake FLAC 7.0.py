import os
import sys
import json
import time
import subprocess
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, scrolledtext
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- CONFIG CACHE ----------
CACHE_FILE = os.path.join(os.path.expanduser("~"), ".flac_scanner_cache.json")
CACHE_VERSION = 1


def carica_cache():
    """Carica la cache da disco. Ritorna dict {cartella: {path: entry}}."""
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('version') != CACHE_VERSION:
            return {}
        return data.get('cartelle', {})
    except Exception:
        return {}


def salva_cache(cache):
    """Salva la cache su disco."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'version': CACHE_VERSION, 'cartelle': cache}, f,
                      ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


# ---------- MOTORE DI CONTROLLO ----------
def identifica_formato_reale(head):
    if head[:4] == b'fLaC':
        return 'FLAC'
    if head[:3] == b'ID3':
        return 'MP3 (tag ID3v2)'
    if head[:2] in (b'\xff\xfb', b'\xff\xfa', b'\xff\xf3', b'\xff\xf2'):
        return 'MP3 (frame raw)'
    if head[:4] == b'OggS':
        return 'OGG (Vorbis/Opus)'
    if head[:4] == b'RIFF':
        return 'WAV'
    if head[:4] == b'MAC ':
        return "Monkey's Audio (APE)"
    if head[:4] == b'wvpk':
        return 'WavPack'
    if head[:4] == b'ADIF' or head[:2] in (b'\xff\xf1', b'\xff\xf9'):
        return 'AAC'
    if head[4:8] == b'ftyp':
        return 'M4A/AAC (MP4)'
    return f'sconosciuto ({head[:4]!r})'


def estensione_per_formato(formato):
    return {
        'MP3 (tag ID3v2)': '.mp3',
        'MP3 (frame raw)': '.mp3',
        'OGG (Vorbis/Opus)': '.ogg',
        'WAV': '.wav',
        "Monkey's Audio (APE)": '.ape',
        'WavPack': '.wv',
        'AAC': '.aac',
        'M4A/AAC (MP4)': '.m4a',
    }.get(formato)


def trova_offset_flac(path, max_bytes=10 * 1024 * 1024):
    try:
        with open(path, 'rb') as f:
            pos = 0
            prev = b''
            while pos < max_bytes:
                chunk = f.read(65536)
                if not chunk:
                    break
                data = prev + chunk
                idx = data.find(b'fLaC')
                if idx != -1:
                    return pos - len(prev) + idx
                prev = chunk[-3:]
                pos += len(chunk)
    except Exception:
        pass
    return -1


def check_flac_header(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(42)
    except Exception as e:
        return ('ERRORE_LETTURA', str(e))

    if len(head) < 42:
        return ('TRONCATO', f'solo {len(head)} byte (minimo 42)')

    if head[:4] != b'fLaC':
        vero = identifica_formato_reale(head)
        pos = trova_offset_flac(path)
        if pos > 0:
            return ('FLAC_CON_TAG_INIZIALE',
                    f'FLAC valido con {pos} byte di tag davanti '
                    f'(player severi mostrano "0 canali")')
        return ('NON_FLAC', f'è in realtà: {vero} — rinominato .flac')

    bh = head[4:8]
    btype = bh[0] & 0x7F
    blen = (bh[1] << 16) | (bh[2] << 8) | bh[3]
    if btype != 0:
        return ('NO_STREAMINFO', f'primo blocco è tipo {btype}, non STREAMINFO(0)')
    if blen != 34:
        return ('STREAMINFO_ANOMALO', f'lunghezza STREAMINFO = {blen} (atteso 34)')

    si = head[8:42]
    v = int.from_bytes(si[10:18], 'big')
    sr = (v >> 44) & 0xFFFFF
    ch = ((v >> 41) & 0x7) + 1
    bps = ((v >> 36) & 0x1F) + 1
    tot = v & 0xFFFFFFFFF

    if sr == 0 or ch == 0 or bps < 4:
        return ('HEADER_CORROTTO', f'sr={sr} ch={ch} bps={bps} (→ "0 canali")')
    if tot == 0:
        return ('DURATA_ZERO', f'sr={sr}Hz {ch}ch {bps}bit total_samples=0')

    return ('OK', f'{sr}Hz {ch}ch {bps}bit')


def flac_deep_test(path):
    try:
        r = subprocess.run(['flac', '-t', '-s', path],
                           capture_output=True, text=True, timeout=300)
        return (r.returncode == 0, r.stderr.strip())
    except FileNotFoundError:
        try:
            r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'],
                               capture_output=True, text=True, timeout=300)
            return (r.returncode == 0, r.stderr.strip())
        except FileNotFoundError:
            return (False, 'né flac né ffmpeg installati')
    except subprocess.TimeoutExpired:
        return (False, 'timeout (>5 min)')


def rinomina_sicura(src, nuova_ext):
    base = os.path.splitext(src)[0]
    dst = base + nuova_ext
    if not os.path.exists(dst):
        os.rename(src, dst)
        return dst
    i = 1
    while True:
        dst = f"{base}_{i}{nuova_ext}"
        if not os.path.exists(dst):
            os.rename(src, dst)
            return dst
        i += 1


def strip_id3_prefix(path):
    offset = trova_offset_flac(path)
    if offset <= 0:
        return (False, f'"fLaC" non trovato o già a offset 0 (offset={offset})', None)

    tmp = path + '.tmp_strip'
    try:
        with open(path, 'rb') as fin:
            fin.seek(offset)
            with open(tmp, 'wb') as fout:
                while True:
                    chunk = fin.read(1024 * 1024)
                    if not chunk:
                        break
                    fout.write(chunk)
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return (False, f'errore scrittura temporaneo: {e}', None)

    stato, det = check_flac_header(tmp)
    if stato != 'OK':
        try:
            os.remove(tmp)
        except Exception:
            pass
        return (False, f'file risultante non valido: {stato} {det}', None)

    backup = path + '.bak'
    try:
        if os.path.exists(backup):
            os.remove(backup)
        os.rename(path, backup)
        os.rename(tmp, path)
    except Exception as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        if os.path.exists(backup) and not os.path.exists(path):
            try:
                os.rename(backup, path)
            except Exception:
                pass
        return (False, f'errore rinomina: {e}', None)

    return (True, f'rimossi {offset} byte (backup: {os.path.basename(backup)})',
            backup)


# ---------- APERTURA / RIPRODUZIONE MULTIPIATTAFORMA ----------
def apri_file_col_player(path):
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return (True, None)
    except Exception as e:
        return (False, str(e))


def apri_cartella(path):
    cart = os.path.dirname(path) or '.'
    try:
        if sys.platform.startswith('win'):
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['xdg-open', cart])
        return (True, None)
    except Exception as e:
        return (False, str(e))


# ---------- INTERFACCIA ----------
class FlacCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trova FLAC danneggiati — Report per cartella (con cache)")
        self.root.geometry("1150x900")
        self.root.configure(bg="#1e1f22")

        self.path_var = tk.StringVar()
        self.deep_var = tk.BooleanVar(value=False)
        self.solo_problemi_var = tk.BooleanVar(value=False)
        self.solo_ripristinabili_var = tk.BooleanVar(value=False)
        self.solo_falsi_var = tk.BooleanVar(value=False)
        self.mostra_ok_var = tk.BooleanVar(value=False)
        self.running = False

        self.last_cartella = None
        self.last_results = None
        self.last_deep_falliti = {}

        # Cache caricata da disco
        self.cache = carica_cache()

        # --- Riga 1: percorso ---
        top = tk.Frame(root, bg="#1e1f22", pady=15, padx=15)
        top.pack(fill="x")
        r1 = tk.Frame(top, bg="#1e1f22")
        r1.pack(fill="x", pady=(0, 10))
        tk.Label(r1, text="Cartella:", bg="#1e1f22", fg="#e6e6e6",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        tk.Entry(r1, textvariable=self.path_var, bg="#383a40", fg="#e6e6e6",
                 insertbackground="white", font=("Segoe UI", 10), relief="flat"
                 ).pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=5)
        self.btn_sfoglia = tk.Button(r1, text="Sfoglia...", command=self.sfoglia,
                                     bg="#0d6efd", fg="white",
                                     font=("Segoe UI", 10, "bold"),
                                     relief="flat", padx=15, cursor="hand2")
        self.btn_sfoglia.pack(side="left", padx=(0, 5))
        self.btn_avvia = tk.Button(r1, text="Avvia Scansione", command=self.avvia,
                                   bg="#198754", fg="white",
                                   font=("Segoe UI", 10, "bold"),
                                   relief="flat", padx=15, cursor="hand2")
        self.btn_avvia.pack(side="left")

        # --- Riga 2: opzioni analisi + cache ---
        r2 = tk.Frame(top, bg="#1e1f22")
        r2.pack(fill="x")
        tk.Checkbutton(r2, text="Verifica approfondita (flac -t / ffmpeg, SOLO sui sospetti FLAC veri)",
                       variable=self.deep_var, bg="#1e1f22", fg="#e6e6e6",
                       selectcolor="#2b2d31", activebackground="#1e1f22",
                       activeforeground="#e6e6e6", font=("Segoe UI", 9)
                       ).pack(side="left")
        tk.Checkbutton(r2, text="Mostra anche i file OK",
                       variable=self.mostra_ok_var,
                       command=self.render_report,
                       bg="#1e1f22", fg="#4ade80", selectcolor="#2b2d31",
                       activebackground="#1e1f22", activeforeground="#4ade80",
                       font=("Segoe UI", 9, "bold")).pack(side="left", padx=(15, 0))

        self.btn_forza = tk.Button(r2, text="🔄 Forza riscansione completa",
                                   command=self.avvia_forzata,
                                   bg="#0e7490", fg="white",
                                   font=("Segoe UI", 9, "bold"),
                                   relief="flat", padx=8, cursor="hand2")
        self.btn_forza.pack(side="right", padx=(5, 0))

        self.btn_svuota = tk.Button(r2, text="🗑️ Svuota cache",
                                    command=self.svuota_cache,
                                    bg="#7f1d1d", fg="white",
                                    font=("Segoe UI", 9, "bold"),
                                    relief="flat", padx=8, cursor="hand2")
        self.btn_svuota.pack(side="right", padx=(5, 0))

        # --- Riga 3: FILTRI ---
        r3 = tk.Frame(top, bg="#1e1f22")
        r3.pack(fill="x", pady=(8, 0))
        tk.Label(r3, text="Filtri report:", bg="#1e1f22", fg="#9ca3af",
                 font=("Segoe UI", 9, "italic")).pack(side="left", padx=(0, 10))

        tk.Checkbutton(r3, text="🔎 Solo problemi (tutti)",
                       variable=self.solo_problemi_var,
                       command=self._filtro_cambiato,
                       bg="#1e1f22", fg="#facc15", selectcolor="#2b2d31",
                       activebackground="#1e1f22", activeforeground="#facc15",
                       font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))

        tk.Checkbutton(r3, text="🟡 Solo ripristinabili",
                       variable=self.solo_ripristinabili_var,
                       command=self._filtro_cambiato,
                       bg="#1e1f22", fg="#facc15", selectcolor="#2b2d31",
                       activebackground="#1e1f22", activeforeground="#facc15",
                       font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))

        tk.Checkbutton(r3, text="🎭 Solo falsi FLAC",
                       variable=self.solo_falsi_var,
                       command=self._filtro_cambiato,
                       bg="#1e1f22", fg="#c084fc", selectcolor="#2b2d31",
                       activebackground="#1e1f22", activeforeground="#c084fc",
                       font=("Segoe UI", 9, "bold")).pack(side="left")

        # --- Riga 4: azioni ---
        r4 = tk.Frame(top, bg="#1e1f22")
        r4.pack(fill="x", pady=(8, 0))

        self.btn_ripristina = tk.Button(r4, text="🔧 Ripristina FLAC tag iniziale",
                                        command=self.ripristina_flac_tag,
                                        bg="#ca8a04", fg="white",
                                        font=("Segoe UI", 9, "bold"),
                                        relief="flat", padx=10, cursor="hand2")
        self.btn_ripristina.pack(side="left", padx=(0, 5))

        self.btn_rinomina = tk.Button(r4, text="🔧 Rinomina falsi FLAC",
                                      command=self.rinomina_falsi_flac,
                                      bg="#be123c", fg="white",
                                      font=("Segoe UI", 9, "bold"),
                                      relief="flat", padx=10, cursor="hand2")
        self.btn_rinomina.pack(side="left", padx=(0, 5))

        self.btn_copia_ripristinabili = tk.Button(r4, text="📋 Copia ripristinabili",
                                                  command=self.copia_lista_ripristinabili,
                                                  bg="#a16207", fg="white",
                                                  font=("Segoe UI", 9, "bold"),
                                                  relief="flat", padx=10, cursor="hand2")
        self.btn_copia_ripristinabili.pack(side="right", padx=(5, 0))

        self.btn_copia_flac = tk.Button(r4, text="🎭 Copia falsi",
                                        command=self.copia_lista_non_flac,
                                        bg="#7c3aed", fg="white",
                                        font=("Segoe UI", 9, "bold"),
                                        relief="flat", padx=10, cursor="hand2")
        self.btn_copia_flac.pack(side="right", padx=(5, 0))

        self.btn_copia_ko = tk.Button(r4, text="📋 Copia tutti KO",
                                      command=self.copia_lista_ko,
                                      bg="#b45309", fg="white",
                                      font=("Segoe UI", 9, "bold"),
                                      relief="flat", padx=10, cursor="hand2")
        self.btn_copia_ko.pack(side="right", padx=(5, 0))

        self.btn_salva = tk.Button(r4, text="💾 Salva report",
                                   command=self.salva_report,
                                   bg="#6c757d", fg="white",
                                   font=("Segoe UI", 9, "bold"),
                                   relief="flat", padx=10, cursor="hand2")
        self.btn_salva.pack(side="right")

        # --- Progress ---
        pf = tk.Frame(root, bg="#1e1f22", padx=15)
        pf.pack(fill="x")
        self.progress_bar = ttk.Progressbar(pf, mode="determinate")
        self.progress_bar.pack(fill="x", pady=5)
        self.status_lbl = tk.Label(pf, text="Pronto.", bg="#1e1f22", fg="#9ca3af",
                                   font=("Segoe UI", 9), anchor="w")
        self.status_lbl.pack(fill="x")
        self.cache_lbl = tk.Label(pf, text="", bg="#1e1f22", fg="#6b7280",
                                  font=("Segoe UI", 9, "italic"), anchor="w")
        self.cache_lbl.pack(fill="x")

        # --- Area testo ---
        self.text_area = scrolledtext.ScrolledText(root, bg="#2b2d31", fg="#e6e6e6",
                                                   font=("Consolas", 11), wrap="none",
                                                   relief="flat", padx=10, pady=10,
                                                   cursor="arrow")
        self.text_area.pack(fill="both", expand=True, padx=15, pady=(10, 15))

        for nome_tag, colore in (
            ("verde", "#4ade80"),
            ("rosso", "#f87171"),
            ("giallo", "#facc15"),
            ("blu", "#38bdf8"),
            ("viola", "#c084fc"),
        ):
            self.text_area.tag_config(nome_tag, foreground=colore,
                                      spacing1=2, spacing3=2)

        self.text_area.tag_config("grassetto", font=("Consolas", 11, "bold"),
                                  spacing1=2, spacing3=2)
        self.text_area.tag_config("corsivo", font=("Consolas", 10, "italic"),
                                  foreground="#9ca3af",
                                  spacing1=2, spacing3=2)
        self.text_area.tag_config("link_file", underline=True,
                                  spacing1=2, spacing3=2)
        self.text_area.tag_config("cartella_titolo", spacing1=10, spacing3=4,
                                  font=("Consolas", 11, "bold"))
        self.text_area.tag_config("base", font=("Consolas", 11),
                                  spacing1=2, spacing3=2)

        self._context_menu = tk.Menu(self.root, tearoff=0,
                                     bg="#2b2d31", fg="#e6e6e6",
                                     activebackground="#0d6efd",
                                     activeforeground="white",
                                     font=("Segoe UI", 10))
        self._context_menu.add_command(label="▶  Riproduci",
                                       command=self._ctx_play)
        self._context_menu.add_command(label="📂  Apri nella cartella",
                                       command=self._ctx_open_folder)
        self._context_menu.add_command(label="📋  Copia percorso",
                                       command=self._ctx_copy_path)
        self._ctx_path = None
        self._tag_to_path = {}

        self.text_area.bind("<Motion>", self._on_motion)
        self.text_area.bind("<Button-3>", self._on_right_click)
        self.text_area.bind("<Button-2>", self._on_right_click)

        # Aggiorna etichetta cache iniziale
        self._aggiorna_cache_lbl()

    # ---------- cache ----------
    def _aggiorna_cache_lbl(self):
        n_cartelle = len(self.cache)
        n_file = sum(len(v) for v in self.cache.values())
        if n_cartelle == 0:
            self.cache_lbl.config(text="📦 Cache: vuota")
        else:
            self.cache_lbl.config(
                text=f"📦 Cache: {n_cartelle} cartell{'a' if n_cartelle == 1 else 'e'}, "
                     f"{n_file} file · {CACHE_FILE}")

    def svuota_cache(self):
        if not self.cache:
            messagebox.showinfo("Cache", "La cache è già vuota.")
            return
        n = sum(len(v) for v in self.cache.values())
        if not messagebox.askyesno("Svuota cache",
                                   f"Eliminare la cache ({len(self.cache)} cartelle, "
                                   f"{n} file)?\n\n"
                                   f"Le prossime scansioni rileggeranno tutto da disco."):
            return
        self.cache = {}
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
        except Exception:
            pass
        self._aggiorna_cache_lbl()
        messagebox.showinfo("Fatto", "Cache svuotata.")

    def avvia_forzata(self):
        self.avvia(forza=True)

    # ---------- utility ----------
    def sfoglia(self):
        p = filedialog.askdirectory(title="Seleziona cartella da scansionare")
        if p:
            self.path_var.set(p)

    def scrivi(self, testo, tag=None):
        self.text_area.insert(tk.END, testo + "\n", tag)
        self.text_area.see(tk.END)
        self.root.update_idletasks()

    def _filtro_cambiato(self):
        if self.solo_ripristinabili_var.get() or self.solo_falsi_var.get():
            self.solo_problemi_var.set(False)
        elif self.solo_problemi_var.get():
            self.solo_ripristinabili_var.set(False)
            self.solo_falsi_var.set(False)
        self.render_report()

    # ---------- click ----------
    def _play_path(self, path):
        ok, err = apri_file_col_player(path)
        if not ok:
            messagebox.showerror("Errore", f"Impossibile aprire il file:\n{err}")

    def _show_ctx(self, event, path):
        self._ctx_path = path
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _on_motion(self, event):
        try:
            index = self.text_area.index(f"@{event.x},{event.y}")
            tags = self.text_area.tag_names(index)
            if any(t.startswith("file_") for t in tags):
                self.text_area.config(cursor="hand2")
            else:
                self.text_area.config(cursor="arrow")
        except Exception:
            pass

    def _on_right_click(self, event):
        index = self.text_area.index(f"@{event.x},{event.y}")
        tags = self.text_area.tag_names(index)
        file_tags = [t for t in tags if t.startswith("file_")]
        if not file_tags:
            return
        path = self._tag_to_path.get(file_tags[0])
        if path:
            self._show_ctx(event, path)

    def _ctx_play(self):
        if self._ctx_path:
            self._play_path(self._ctx_path)

    def _ctx_open_folder(self):
        if self._ctx_path:
            ok, err = apri_cartella(self._ctx_path)
            if not ok:
                messagebox.showerror("Errore", f"Impossibile aprire la cartella:\n{err}")

    def _ctx_copy_path(self):
        if self._ctx_path:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._ctx_path)

    # ---------- liste ----------
    def _lista_ko(self):
        if not self.last_results:
            return []
        return [p for p, stato, _ in self.last_results if stato != 'OK']

    def _lista_non_flac(self):
        if not self.last_results:
            return []
        return [p for p, stato, _ in self.last_results if stato == 'NON_FLAC']

    def _lista_ripristinabili(self):
        if not self.last_results:
            return []
        return [p for p, stato, _ in self.last_results
                if stato == 'FLAC_CON_TAG_INIZIALE']

    def copia_lista_ko(self):
        if not self.last_results:
            messagebox.showinfo("Nessun dato", "Esegui prima una scansione.")
            return
        ko = self._lista_ko()
        if not ko:
            messagebox.showinfo("Nessun problema", "Nessun file problematico.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(ko))
        messagebox.showinfo("Copiato", f"{len(ko)} percorsi copiati negli appunti.")

    def copia_lista_non_flac(self):
        if not self.last_results:
            messagebox.showinfo("Nessun dato", "Esegui prima una scansione.")
            return
        lst = self._lista_non_flac()
        if not lst:
            messagebox.showinfo("Nessun falso FLAC",
                                "Nessun file .flac è in realtà un altro formato.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lst))
        messagebox.showinfo("Copiato", f"{len(lst)} percorsi copiati negli appunti.")

    def copia_lista_ripristinabili(self):
        if not self.last_results:
            messagebox.showinfo("Nessun dato", "Esegui prima una scansione.")
            return
        lst = self._lista_ripristinabili()
        if not lst:
            messagebox.showinfo("Nessun ripristinabile",
                                "Nessun file classificato come 'FLAC con tag iniziale'.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lst))
        messagebox.showinfo("Copiato", f"{len(lst)} percorsi copiati negli appunti.")

    def salva_report(self):
        contenuto = self.text_area.get("1.0", tk.END)
        if not contenuto.strip():
            messagebox.showinfo("Vuoto", "Nessun report da salvare.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".txt",
                                         filetypes=[("Testo", "*.txt"), ("Tutti", "*.*")],
                                         initialfile="report_flac.txt")
        if f:
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write(contenuto)
            messagebox.showinfo("Salvato", f"Report salvato in:\n{f}")

    # ---------- ripristino (thread + progress) ----------
    def ripristina_flac_tag(self):
        if not self.last_results:
            messagebox.showinfo("Nessun dato", "Esegui prima una scansione.")
            return
        if self.running:
            messagebox.showinfo("Attendere", "Operazione già in corso.")
            return

        da_ripristinare = self._lista_ripristinabili()
        if not da_ripristinare:
            messagebox.showinfo("Nessun caso",
                                "Nessun file classificato come 'FLAC con tag iniziale'.")
            return

        preview = "\n".join(f"  {os.path.basename(p)}" for p in da_ripristinare[:20])
        if len(da_ripristinare) > 20:
            preview += f"\n  ... e altri {len(da_ripristinare) - 20}"

        msg = (f"Verranno ripristinati {len(da_ripristinare)} file FLAC rimuovendo "
               f"il tag ID3 preposto.\n\n"
               f"L'originale verrà salvato come <nome>.flac.bak.\n\n"
               f"File coinvolti:\n{preview}\n\nProcedere?")
        if not messagebox.askyesno("Conferma ripristino", msg):
            return

        self.running = True
        self.btn_avvia.config(state="disabled")
        self.btn_sfoglia.config(state="disabled")
        self.btn_ripristina.config(state="disabled")
        self.btn_rinomina.config(state="disabled")
        self.btn_forza.config(state="disabled")
        self.btn_svuota.config(state="disabled")
        self.progress_bar["value"] = 0
        self.status_lbl.config(text=f"Ripristino in corso: 0/{len(da_ripristinare)}...")

        self.scrivi("\n=== RIPRISTINO FLAC CON TAG INIZIALE ===", "blu")
        self.scrivi(f"File da ripristinare: {len(da_ripristinare)}\n", "grassetto")

        threading.Thread(target=self._ripristina_worker,
                         args=(da_ripristinare,), daemon=True).start()

    def _ripristina_worker(self, da_ripristinare):
        fatti = 0
        errori = []
        totale = len(da_ripristinare)

        for i, p in enumerate(da_ripristinare, 1):
            try:
                ok, msg_res, _ = strip_id3_prefix(p)
                if ok:
                    fatti += 1
                    stato, det = check_flac_header(p)
                    self.last_results = [
                        (path, stato if path == p else st, det if path == p else d)
                        for (path, st, d) in self.last_results
                    ]
                    self.last_deep_falliti.pop(p, None)

                    # Aggiorna cache per questo file
                    self._aggiorna_cache_file(p, stato, det)

                    rel = (os.path.relpath(p, self.last_cartella)
                           if self.last_cartella else p)
                    self.root.after(0, lambda m=rel: self.scrivi(f"  ✅ {m}", "verde"))
                else:
                    errori.append((p, msg_res))
                    rel = (os.path.relpath(p, self.last_cartella)
                           if self.last_cartella else p)
                    self.root.after(0, lambda m=rel, e=msg_res: self.scrivi(
                        f"  ❌ {m} → {e}", "rosso"))
            except Exception as e:
                errori.append((p, str(e)))
                rel = (os.path.relpath(p, self.last_cartella)
                       if self.last_cartella else p)
                self.root.after(0, lambda m=rel, e=str(e): self.scrivi(
                    f"  ❌ {m} → {e}", "rosso"))

            pct = (i / totale) * 100
            self.root.after(0, lambda v=pct, ii=i, tt=totale: (
                self.progress_bar.configure(value=v),
                self.status_lbl.config(
                    text=f"Ripristino: {ii}/{tt} ({v:.0f}%)"),
            ))

        # salva cache aggiornata
        salva_cache(self.cache)
        self.root.after(0, self._aggiorna_cache_lbl)

        def fine():
            self.scrivi(f"\nRipristinati: {fatti}", "verde")
            if errori:
                self.scrivi(f"Errori: {len(errori)}", "rosso")
                for p, e in errori:
                    self.scrivi(f"  ❌ {os.path.basename(p)}: {e}", "rosso")
            self.progress_bar["value"] = 100
            self.status_lbl.config(text=f"Ripristino completato: {fatti}/{totale}")
            self.render_report()
            self.running = False
            self.btn_avvia.config(state="normal", text="Avvia Scansione")
            self.btn_sfoglia.config(state="normal")
            self.btn_ripristina.config(state="normal")
            self.btn_rinomina.config(state="normal")
            self.btn_forza.config(state="normal")
            self.btn_svuota.config(state="normal")
            messagebox.showinfo("Fatto",
                                f"Ripristinati {fatti} file."
                                + (f"\nErrori: {len(errori)}" if errori else ""))

        self.root.after(0, fine)

    def _aggiorna_cache_file(self, path, stato, det):
        """Aggiorna la entry cache per un singolo file."""
        if not self.last_cartella:
            return
        cart_key = os.path.normcase(os.path.abspath(self.last_cartella))
        entry_cart = self.cache.setdefault(cart_key, {})
        try:
            st = os.stat(path)
            entry_cart[path] = {
                'mtime': st.st_mtime,
                'size': st.st_size,
                'stato': stato,
                'det': det,
            }
        except Exception:
            pass

    # ---------- rinomina ----------
    def rinomina_falsi_flac(self):
        if not self.last_results:
            messagebox.showinfo("Nessun dato", "Esegui prima una scansione.")
            return
        if self.running:
            messagebox.showinfo("Attendere", "Operazione già in corso.")
            return
        falsi = self._lista_non_flac()
        if not falsi:
            messagebox.showinfo("Nessun falso FLAC",
                                "Nessun file .flac è in realtà un altro formato.")
            return

        piano = []
        sconosciuti = []
        for p in falsi:
            try:
                with open(p, 'rb') as f:
                    head = f.read(42)
                fmt = identifica_formato_reale(head)
                ext = estensione_per_formato(fmt)
                if ext:
                    piano.append((p, ext, fmt))
                else:
                    sconosciuti.append((p, fmt))
            except Exception as e:
                sconosciuti.append((p, f'errore lettura: {e}'))

        if not piano and not sconosciuti:
            return

        preview = []
        for p, ext, fmt in piano[:25]:
            preview.append(f"  {os.path.basename(p)}  →  {ext}  ({fmt})")
        if len(piano) > 25:
            preview.append(f"  ... e altri {len(piano) - 25} file")
        if sconosciuti:
            preview.append("")
            preview.append(f"⚠️  {len(sconosciuti)} file con formato non riconosciuto "
                           f"(NON verranno rinominati):")
            for p, fmt in sconosciuti[:10]:
                preview.append(f"  {os.path.basename(p)}  ({fmt})")

        msg = (f"Verranno rinominati {len(piano)} file .flac "
               f"con l'estensione corretta.\n\n"
               f"Anteprima:\n" + "\n".join(preview) + "\n\nProcedere?")
        if not messagebox.askyesno("Conferma rinomina", msg):
            return

        rinominati = []
        errori = []
        for src, ext, fmt in piano:
            try:
                dst = rinomina_sicura(src, ext)
                if dst:
                    rinominati.append((src, dst))
                else:
                    errori.append((src, 'rename ha restituito None'))
            except Exception as e:
                errori.append((src, str(e)))

        src_rinominati = {s for s, _ in rinominati}
        self.last_results = [(p, st, d) for (p, st, d) in self.last_results
                             if p not in src_rinominati]
        for s in src_rinominati:
            self.last_deep_falliti.pop(s, None)

        # Rimuovi i rinominati anche dalla cache
        if self.last_cartella:
            cart_key = os.path.normcase(os.path.abspath(self.last_cartella))
            entry_cart = self.cache.get(cart_key, {})
            for s in src_rinominati:
                entry_cart.pop(s, None)
            salva_cache(self.cache)
            self._aggiorna_cache_lbl()

        self.scrivi("\n=== RINOMINA FALSI FLAC ===", "blu")
        self.scrivi(f"Rinominati: {len(rinominati)}", "verde")
        if errori:
            self.scrivi(f"Errori: {len(errori)}", "rosso")
            for p, e in errori:
                self.scrivi(f"  ❌ {os.path.basename(p)}: {e}", "rosso")
        if sconosciuti:
            self.scrivi(f"Non rinominati (formato sconosciuto): {len(sconosciuti)}",
                        "giallo")

        self.render_report()
        messagebox.showinfo("Fatto",
                            f"Rinominati {len(rinominati)} file."
                            + (f"\nErrori: {len(errori)}" if errori else "")
                            + (f"\nNon riconosciuti: {len(sconosciuti)}"
                               if sconosciuti else ""))

    # ---------- avvio ----------
    def avvia(self, forza=False):
        if self.running:
            return
        cartella = self.path_var.get().strip().strip('"').strip("'")
        if not cartella or not os.path.isdir(cartella):
            messagebox.showerror("Errore", "Seleziona una cartella valida.")
            return
        self.running = True
        self.text_area.delete("1.0", tk.END)
        self.btn_avvia.config(state="disabled", text="Scansione...")
        self.btn_sfoglia.config(state="disabled")
        self.btn_forza.config(state="disabled")
        self.btn_svuota.config(state="disabled")
        self.progress_bar["value"] = 0
        self.last_results = None
        self.last_deep_falliti = {}
        threading.Thread(target=self.scansiona,
                         args=(cartella, self.deep_var.get(), forza),
                         daemon=True).start()

    # ---------- scansione (con cache) ----------
    def scansiona(self, cartella, deep, forza):
        t_inizio = time.time()
        self.scrivi(f"=== SCANSIONE: {cartella} ===", "blu")
        self.scrivi(f"Modalità: {'APPROFONDITA' if deep else 'RAPIDA'}"
                    f"{' (CACHE IGNORATA)' if forza else ''}\n", "corsivo")

        self.status_lbl.config(text="Raccolta file .flac...")
        files = []
        for root_dir, _, fs in os.walk(cartella):
            for f in fs:
                if f.lower().endswith('.flac'):
                    files.append(os.path.join(root_dir, f))

        if not files:
            self.scrivi("Nessun file .flac trovato.", "giallo")
            self.last_results = []
            self.last_cartella = cartella
            self.root.after(0, self._fine)
            return

        self.scrivi(f"Trovati {len(files)} file .flac da scansionare "
                    f"(totale, non solo problemi)\n", "grassetto")

        # Carica cache per questa cartella
        cart_key = os.path.normcase(os.path.abspath(cartella))
        cache_cart = {} if forza else self.cache.get(cart_key, {})

        self.status_lbl.config(text="Fase 1: lettura header (con cache)...")
        risultati = []
        da_cache = 0
        da_disco = 0
        nuovi = []
        cache_nuova = {}  # per la cartella corrente

        for i, p in enumerate(files, 1):
            try:
                st = os.stat(p)
                mtime, size = st.st_mtime, st.st_size
            except Exception:
                mtime, size = 0, 0

            entry = cache_cart.get(p)
            if (entry and not forza
                    and entry.get('mtime') == mtime
                    and entry.get('size') == size):
                # HIT cache
                stato = entry['stato']
                det = entry['det']
                da_cache += 1
                risultati.append((p, stato, det))
                cache_nuova[p] = entry
            else:
                # MISS: leggi da disco
                stato, det = check_flac_header(p)
                da_disco += 1
                risultati.append((p, stato, det))
                cache_nuova[p] = {
                    'mtime': mtime, 'size': size,
                    'stato': stato, 'det': det,
                }
                nuovi.append((p, stato, det))

            if i % 100 == 0 or i == len(files):
                self.progress_bar["value"] = (i / len(files)) * (40 if deep else 100)
                self.status_lbl.config(
                    text=f"Fase 1: {i}/{len(files)}  "
                         f"(cache: {da_cache}, disco: {da_disco})")
                self.root.update_idletasks()

        # Salva la cache aggiornata per questa cartella
        self.cache[cart_key] = cache_nuova
        salva_cache(self.cache)
        self.root.after(0, self._aggiorna_cache_lbl)

        # Messaggio di hit/miss
        self.scrivi(f"\n📦 Cache: {da_cache} file dalla cache, "
                    f"{da_disco} riletti da disco", "corsivo")

        # FASE 2 (solo su sospetti, non cachata)
        sospetti = [r for r in risultati if r[1] not in ('OK', 'FLAC_CON_TAG_INIZIALE')]
        sospetti_deep = [r for r in sospetti if r[1] != 'NON_FLAC']
        saltati_non_flac = len(sospetti) - len(sospetti_deep)

        deep_falliti = {}
        if deep and sospetti_deep:
            self.scrivi(f"\n--- FASE 2: VERIFICA APPROFONDITA (non cachata) ---", "blu")
            self.scrivi(f"File sospetti FLAC da verificare: {len(sospetti_deep)}",
                        "corsivo")
            if saltati_non_flac:
                self.scrivi(f"File NON_FLAC saltati (già identificati): "
                            f"{saltati_non_flac}", "corsivo")
            self.scrivi("", None)

            self.status_lbl.config(text=f"Fase 2: verifica {len(sospetti_deep)} file...")
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(flac_deep_test, r[0]): r[0] for r in sospetti_deep}
                done = 0
                for fut in as_completed(futures):
                    p = futures[fut]
                    ok, msg = fut.result()
                    done += 1
                    if not ok:
                        deep_falliti[p] = msg or 'errore decodifica'
                        rel = os.path.relpath(p, cartella)
                        self.root.after(0, lambda m=rel, e=msg: self.scrivi(
                            f"  ❌ {m} → {e[:80]}", "rosso"))
                    self.progress_bar["value"] = 40 + (done / len(sospetti_deep)) * 60
                    self.status_lbl.config(text=f"Fase 2: {done}/{len(sospetti_deep)}")
                    self.root.update_idletasks()

            self.scrivi(f"\nVerifica completata: "
                        f"{len(sospetti_deep) - len(deep_falliti)} OK, "
                        f"{len(deep_falliti)} KO",
                        "verde" if not deep_falliti else "rosso")

        self.progress_bar["value"] = 100
        elapsed = time.time() - t_inizio
        self.status_lbl.config(text=f"Completato in {elapsed:.1f}s")
        self.last_cartella = cartella
        self.last_results = risultati
        self.last_deep_falliti = deep_falliti

        def fine_scan():
            self._aggiorna_cache_lbl()
            self.render_report()
            self._fine()
        self.root.after(0, fine_scan)

    # ---------- rendering report ----------
    def render_report(self):
        if not self.last_results or self.last_cartella is None:
            return
        cartella = self.last_cartella
        risultati = self.last_results
        deep_falliti = self.last_deep_falliti

        solo_problemi = self.solo_problemi_var.get()
        solo_ripristinabili = self.solo_ripristinabili_var.get()
        solo_falsi = self.solo_falsi_var.get()
        mostra_ok = self.mostra_ok_var.get()
        filtro_attivo = solo_problemi or solo_ripristinabili or solo_falsi

        self.text_area.delete("1.0", tk.END)
        self._tag_to_path = {}

        self.scrivi(f"=== SCANSIONE: {cartella} ===", "blu")
        if solo_ripristinabili:
            etichetta = "SOLO RIPRISTINABILI (FLAC con tag iniziale)"
        elif solo_falsi:
            etichetta = "SOLO FALSI FLAC"
        elif solo_problemi:
            etichetta = "SOLO CARTELLE CON PROBLEMI (tutti)"
        else:
            etichetta = "tutte le cartelle"
        self.scrivi(f"Filtro: {etichetta}\n", "corsivo")
        self.scrivi("💡 Doppio click su un file per riprodurlo · tasto destro per menu\n",
                    "corsivo")

        per_cartella = {}
        for p, stato, det in risultati:
            per_cartella.setdefault(os.path.dirname(p), []).append((p, stato, det))

        totale_ok = 0
        totale_ko = 0
        totale_nonflac = 0
        totale_tag_iniziale = 0
        cartelle_con_problemi = 0
        cartelle_mostrate = 0

        self.scrivi("=== REPORT PER CARTELLA ===\n", "blu")
        self.scrivi("Legenda:  ✅ OK  |  🟡 ripristinabile  |  "
                    "🎭 falso FLAC  |  ❌ danneggiato\n", "corsivo")

        for cart in sorted(per_cartella.keys()):
            voci = per_cartella[cart]
            ok_voci = [v for v in voci if v[1] == 'OK']
            tag_iniz = [v for v in voci if v[1] == 'FLAC_CON_TAG_INIZIALE']
            nonflac_voci = [v for v in voci if v[1] == 'NON_FLAC']
            ko_voci = [v for v in voci
                       if v[1] not in ('OK', 'FLAC_CON_TAG_INIZIALE', 'NON_FLAC')]
            problemi = tag_iniz + nonflac_voci + ko_voci
            ok_count = len(ok_voci)

            totale_ok += ok_count
            totale_tag_iniziale += len(tag_iniz)
            totale_nonflac += len(nonflac_voci)
            totale_ko += len(ko_voci)
            if problemi:
                cartelle_con_problemi += 1

            if solo_ripristinabili:
                if not tag_iniz:
                    continue
            elif solo_falsi:
                if not nonflac_voci:
                    continue
            elif solo_problemi:
                if not problemi:
                    continue

            cartelle_mostrate += 1
            rel = os.path.relpath(cart, cartella)
            if rel == '.':
                rel = os.path.basename(cartella) or cartella

            if not problemi:
                self.text_area.insert(tk.END,
                    f"📁 {rel}  —  ✅ {ok_count} OK\n",
                    ("verde", "cartella_titolo"))
            else:
                pezzi = [f"✅ {ok_count} OK"]
                if tag_iniz:
                    pezzi.append(f"🟡 {len(tag_iniz)} da ripristinare")
                if nonflac_voci:
                    pezzi.append(f"🎭 {len(nonflac_voci)} falsi")
                if ko_voci:
                    pezzi.append(f"❌ {len(ko_voci)} danneggiati")
                self.text_area.insert(tk.END,
                    f"📁 {rel}  —  " + "  ".join(pezzi) + "\n",
                    ("rosso", "cartella_titolo"))
            self.text_area.see(tk.END)

            if problemi:
                if solo_ripristinabili:
                    voci_da_mostrare = tag_iniz
                elif solo_falsi:
                    voci_da_mostrare = nonflac_voci
                else:
                    voci_da_mostrare = problemi

                for p, stato, det in voci_da_mostrare:
                    self._scrivi_riga_file(p, stato, det, deep_falliti)

                if mostra_ok and ok_voci and not filtro_attivo:
                    for p, stato, det in ok_voci:
                        self._scrivi_riga_file(p, stato, det, deep_falliti)

            if not problemi and mostra_ok and not filtro_attivo:
                for p, stato, det in ok_voci:
                    self._scrivi_riga_file(p, stato, det, deep_falliti)

        if filtro_attivo and cartelle_mostrate == 0:
            self.scrivi("🎉 Nessun risultato per il filtro attivo.", "verde")

        self.scrivi("\n=== RIEPILOGO GENERALE ===", "blu")
        self.scrivi(f"File totali scansionati: {len(risultati)}", "grassetto")
        self.scrivi(f"✅ OK: {totale_ok}", "verde")
        self.scrivi(f"🟡 FLAC con tag iniziale (ripristinabili): {totale_tag_iniziale}",
                    "giallo" if totale_tag_iniziale else "verde")
        self.scrivi(f"🎭 Falsi FLAC (altro formato): {totale_nonflac}",
                    "viola" if totale_nonflac else "verde")
        self.scrivi(f"❌ Danneggiati veri: {totale_ko}",
                    "rosso" if totale_ko else "verde")
        self.scrivi(f"📁 Cartelle con problemi: {cartelle_con_problemi} / {len(per_cartella)}",
                    "rosso" if cartelle_con_problemi else "verde")
        if filtro_attivo:
            self.scrivi(f"📁 Cartelle mostrate (dopo filtro): {cartelle_mostrate}",
                        "giallo")
        if mostra_ok:
            self.scrivi("ℹ️  File OK mostrati nell'elenco "
                        "(checkbox 'Mostra anche i file OK' attivo)", "corsivo")

    def _scrivi_riga_file(self, p, stato, det, deep_falliti):
        nome = os.path.basename(p)
        extra = ""
        if p in deep_falliti:
            extra = f"   [deep: {deep_falliti[p][:70]}]"

        if stato == 'OK':
            tag = "verde"
            riga = f"     ✅ {nome}   [{det}]"
        elif stato == 'FLAC_CON_TAG_INIZIALE':
            tag = "giallo"
            riga = f"     🟡 {nome}   [{stato}]  {det}"
        elif stato == 'NON_FLAC':
            tag = "viola"
            riga = f"     🎭 {nome}   [{stato}]  {det}"
        else:
            tag = "rosso"
            riga = f"     ❌ {nome}   [{stato}]  {det}{extra}"

        start = self.text_area.index("end-1c")
        self.text_area.insert(tk.END, riga + "\n", (tag, "link_file"))
        end = self.text_area.index("end-1c linestart")

        tag_univoco = f"file_{abs(hash(p)) & 0xFFFFFFFF}_{id(p)}"
        self.text_area.tag_add(tag_univoco, start, end)
        self._tag_to_path[tag_univoco] = p

        self.text_area.tag_bind(tag_univoco, "<Double-Button-1>",
                                lambda e, pp=p: self._play_path(pp))
        self.text_area.tag_bind(tag_univoco, "<Button-3>",
                                lambda e, pp=p: self._show_ctx(e, pp))
        self.text_area.tag_bind(tag_univoco, "<Button-2>",
                                lambda e, pp=p: self._show_ctx(e, pp))

        self.text_area.see(tk.END)

    def _fine(self):
        def reset():
            self.running = False
            self.btn_avvia.config(state="normal", text="Avvia Scansione")
            self.btn_sfoglia.config(state="normal")
            self.btn_forza.config(state="normal")
            self.btn_svuota.config(state="normal")
        self.root.after(0, reset)


if __name__ == "__main__":
    root = tk.Tk()
    app = FlacCheckerApp(root)
    root.mainloop()