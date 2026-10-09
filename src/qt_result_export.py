"""Reusable exports of actual calculation data and saved run directories."""
import shutil
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog

def export_frame(parent,frame,status,filename='results.csv'):
    if frame is None or frame.empty:
        status.setText('Calculate or load results before exporting.');return
    path,_=QFileDialog.getSaveFileName(parent,'Export results',filename,'CSV (*.csv)')
    if not path:return
    try:
        frame.to_csv(path,index=False)
        status.setText(f'Exported {len(frame):,} rows to {path}.')
    except OSError as exc:status.setText('Could not export results: '+str(exc))

def export_run(parent,directory,status):
    if directory is None or not Path(directory).is_dir():
        status.setText('Run or open a saved campaign before exporting.');return
    path,_=QFileDialog.getSaveFileName(parent,'Export saved campaign','campaign.zip','ZIP archive (*.zip)')
    if not path:return
    target=Path(path)
    if target.suffix.lower()!='.zip':target=target.with_suffix('.zip')
    if target.resolve().is_relative_to(Path(directory).resolve()):
        status.setText('Choose an export location outside the saved run directory.');return
    try:
        shutil.make_archive(str(target.with_suffix('')),'zip',directory)
        status.setText(f'Exported saved campaign to {target}.')
    except OSError as exc:status.setText('Could not export campaign: '+str(exc))
