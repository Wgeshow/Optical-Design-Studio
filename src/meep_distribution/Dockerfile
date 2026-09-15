# Supply a reviewed Linux x86_64 base by immutable image digest.
# A Miniforge base supplies conda and standard Linux utilities; no host WSL
# settings or distributions are touched by this image build.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY linux-64.explicit.txt /opt/ods-build/linux-64.explicit.txt
COPY rootfs_self_test.py /opt/ods-build/rootfs_self_test.py
RUN /opt/conda/bin/conda create --yes --prefix /opt/ods-meep --file /opt/ods-build/linux-64.explicit.txt \
    && /opt/ods-meep/bin/python /opt/ods-build/rootfs_self_test.py \
    && useradd --create-home --uid 1000 --shell /bin/bash ods \
    && mkdir -p /usr/share/ods-fdtd/licenses /usr/share/ods-fdtd/package-metadata \
    && /opt/conda/bin/python -c "import pathlib,shutil; target=pathlib.Path('/usr/share/ods-fdtd'); [(shutil.copytree(p/'info'/'licenses',target/'licenses'/p.name,dirs_exist_ok=True) if (p/'info'/'licenses').is_dir() else None) for p in pathlib.Path('/opt/conda/pkgs').iterdir() if p.is_dir()]; [shutil.copy2(p,target/'package-metadata'/p.name) for p in pathlib.Path('/opt/ods-meep/conda-meta').glob('*.json')]" \
    && printf '[user]\ndefault=ods\n[automount]\nenabled=true\nroot=/mnt/\n[interop]\nenabled=false\nappendWindowsPath=false\n' > /etc/wsl.conf \
    && /opt/conda/bin/conda list --prefix /opt/ods-meep --explicit --md5 > /usr/share/ods-fdtd/linux-64.explicit.txt \
    && /opt/conda/bin/conda clean --all --yes
WORKDIR /home/ods
USER ods
ENTRYPOINT []
CMD ["/bin/bash"]
