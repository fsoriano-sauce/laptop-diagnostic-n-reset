# Dell\Drivers — driver packages staged at install time

`stage.ps1` runs during the Windows specialize pass and installs, with
`pnputil`, every `.inf` found under the folder whose name matches the
laptop's model plus anything under `Common`. Folder contents are not
committed to git (multi-GB). Layout:

```
Dell/Drivers/
├── Common/            # applies to every unit (e.g. Intel Wi-Fi/Bluetooth)
├── Vostro 7620/       # matched against Win32_ComputerSystem.Model
├── Vostro 15 7510/
└── Vostro 7500/
```

Matching is loose: the folder name and the model string are compared with
punctuation and spaces removed, so `Vostro7510` also matches `Vostro 15 7510`.

## Where the packages come from

Dell does not publish enterprise driver-pack CABs for Vostro. Download the
individual packages from each model's support page, Windows 11, category
filter as listed, and drop the `.exe` files in `Dell/Downloads/<Model>/`.
Then run `build_restorer.ps1 -ExtractDups`.

- Vostro 7620: https://www.dell.com/support/product-details/en-us/product/vostro-16-7620-laptop/drivers
- Vostro 15 7510: https://www.dell.com/support/product-details/en-us/product/vostro-15-7510-laptop/drivers
- Vostro 7500: https://www.dell.com/support/product-details/en-us/product/vostro-15-7500-laptop/drivers

Minimum set, in priority order. Everything below the line arrives through
Windows Update once the buyer connects, so it is optional.

| Priority | Category on Dell's page | Why |
|---|---|---|
| must | Network: Intel Wi-Fi 6/6E driver | Wi-Fi must work at the OOBE network screen |
| must | Network: Intel Bluetooth | Windows Hello / peripherals at first boot |
| should | Security: Goodix / Synaptics fingerprint | Windows Hello enrolment during OOBE |
| should | Audio: Realtek High Definition Audio | Speakers work before Windows Update runs |
| should | Chipset: Intel Serial IO, Intel Chipset Device Software | touchpad and sensors without "unknown device" entries |
| nice | Video: Intel Iris Xe/UHD, NVIDIA GeForce | correct resolution and GPU at first boot (large downloads) |
| nice | Chipset: Intel Management Engine, Thunderbolt | clean Device Manager |

The `Dell\Reports\<ServiceTag>.txt` file written to the USB after each
install lists every device still lacking a driver. Add packages until that
list is empty for each model, then stop.

Packages that do not extract with `/s /e=` open fine in 7-Zip; copy the
folder that holds the `.inf` files into `Dell/Drivers/<Model>/<name>/`.
