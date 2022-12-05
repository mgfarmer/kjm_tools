package org.kjm.tools;

import java.awt.AWTException;
import java.awt.Frame;
import java.awt.Image;
import java.awt.MenuItem;
import java.awt.PopupMenu;
import java.awt.SystemTray;
import java.awt.Toolkit;
import java.awt.TrayIcon;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.io.IOException;

public class SshTunnelTray extends Frame {
	/**
	 * 
	 */
	private static final long serialVersionUID = 1L;
	private enum TUNNEL { Open, Closed; 
		public TUNNEL toggle() {
			if (this == Open) return Closed; else return Open;
		}
	};
	
	TrayIcon trayIcon = null;
	private PopupMenu popup;
	TUNNEL currentState = TUNNEL.Closed;
	private SystemTray tray;
	private Image imageClosed;
	private Image imageOpen;
	

	public SshTunnelTray(String[] args) {
		if (SystemTray.isSupported()) {
			imageOpen = Toolkit.getDefaultToolkit().getImage(getClass().getResource("tunnel-open.png"));
			imageClosed = Toolkit.getDefaultToolkit().getImage(getClass().getResource("tunnel-closed.png"));
			
			command = String.join(" ", args);

			ActionListener listener = new ActionListener() {
				public void actionPerformed(ActionEvent e) {
					setState(currentState.toggle());
				}
			};

			MenuItem defaultItem = new MenuItem("Toggle Tunnel");
			defaultItem.addActionListener(listener);

			popup = new PopupMenu();
			popup.add(defaultItem);

			MenuItem exitItem = new MenuItem("Exit");
			exitItem.addActionListener(new ActionListener() {
				
				@Override
				public void actionPerformed(ActionEvent e) {
					if (sshProcess != null) {
						sshProcess.destroy();
					}
					System.exit(0);
				}
			});
			popup.add(exitItem);
			
			tray = SystemTray.getSystemTray();

			trayIcon = new TrayIcon(imageOpen, "Tunnel Open", popup);
			trayIcon.addActionListener(listener);

			try {
				tray.add(trayIcon);
			} catch (AWTException e1) {
				e1.printStackTrace();
			}
			setState(TUNNEL.Closed);
		}
		else {
			System.out.println("Java SystemTray is not support here!");
			System.exit(1);
		}
	}

	public static void main(String[] args) {
		if (args.length == 0) {
			System.out.println("You need to specify the ssh command tha twill initiate the tunnel.");
			System.exit(1);
		}
		new SshTunnelTray(args);
	}

	Process sshProcess = null;

	private String command;
	private void setState(TUNNEL state) {
		currentState = state;
		if (currentState == TUNNEL.Closed) {
			if (sshProcess != null) {
				sshProcess.destroy();
				//System.out.println("terminating tunnel");
			}
			sshProcess = null;
		}
		else {
            Runtime run  = Runtime.getRuntime();
            try {
            	//System.out.println("opening tunnel");
            	//System.out.println("cmd: " + command);
				sshProcess = run.exec(command);
			} catch (IOException e) {
				e.printStackTrace();
			}
		}
		trayIcon.setImage(currentState==TUNNEL.Open ? imageOpen : imageClosed);
		trayIcon.setToolTip("Tunnel is " + (currentState==TUNNEL.Open ? "open":"closed"));
	}
}
