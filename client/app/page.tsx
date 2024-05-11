'use client'
import { Box, Button, CssBaseline, Dialog, DialogActions, DialogTitle, Divider, Drawer, IconButton, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Modal, TextField, Toolbar, Typography, styled, useTheme } from "@mui/material";
import MenuIcon from '@mui/icons-material/Menu';
import MuiAppBar, { AppBarProps as MuiAppBarProps } from '@mui/material/AppBar';
import {  useState } from "react";
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import InboxIcon from '@mui/icons-material/MoveToInbox';
import MailIcon from '@mui/icons-material/Mail';

import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Paper from '@mui/material/Paper';
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import axios from "axios";
import { StatusIcon } from "./[id]/page";

const drawerWidth = 240;

const Main = styled('main', { shouldForwardProp: (prop) => prop !== 'open' })<{
  open?: boolean;
}>(({ theme, open }) => ({
  flexGrow: 1,
  padding: theme.spacing(3),
  transition: theme.transitions.create('margin', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  marginLeft: `-${drawerWidth}px`,
  ...(open && {
    transition: theme.transitions.create('margin', {
      easing: theme.transitions.easing.easeOut,
      duration: theme.transitions.duration.enteringScreen,
    }),
    marginLeft: 0,
  }),
}));

interface AppBarProps extends MuiAppBarProps {
  open?: boolean;
}

const AppBar = styled(MuiAppBar, {
  shouldForwardProp: (prop) => prop !== 'open',
})<AppBarProps>(({ theme, open }) => ({
  transition: theme.transitions.create(['margin', 'width'], {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  ...(open && {
    width: `calc(100% - ${drawerWidth}px)`,
    marginLeft: `${drawerWidth}px`,
    transition: theme.transitions.create(['margin', 'width'], {
      easing: theme.transitions.easing.easeOut,
      duration: theme.transitions.duration.enteringScreen,
    }),
  }),
}));

const DrawerHeader = styled('div')(({ theme }) => ({
  display: 'flex',
  alignItems: 'center',
  padding: theme.spacing(0, 1),
  // necessary for content to be below app bar
  ...theme.mixins.toolbar,
  justifyContent: 'flex-end',
}));

export default function Home() {
  const router = useRouter()
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  
  const {data: scenarioList } = useQuery<{_id:string, scenario_name:string, run_status:string}[]>({queryKey: ['scenarios'], queryFn: async () => {
    const data = await fetch('http://127.0.0.1:5000/e2e/scenarios');
    return data.json();
  }})

  const {mutate:postRunAll, isPending:isRunPending} = useMutation({mutationFn: async () => {
    return axios.post(`http://127.0.0.1:5000/e2e/scenarios/run-all`);
  }},);



  const handleScenarioAdd = () => {
    setIsModalOpen(true);
  }

  const handleDrawerOpen = () => {
    setOpen(true);
  };

  const handleDrawerClose = () => {
    setOpen(false);
  };

  const handleScenarioRunAll = () => {
    postRunAll()
  }



  return (
    

    <>
    
    <Box sx={{ display: 'flex', height:"100%" }}>
      <CssBaseline />
      <AppBar position="fixed" open={open}>
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            onClick={handleDrawerOpen}
            edge="start"
            sx={{ mr: 2, ...(open && { display: 'none' }) }}
          >
            <MenuIcon />
          </IconButton>
          

          <Typography variant="h6" noWrap component="div">
            QA 시나리오
          </Typography>

          
        </Toolbar>
      </AppBar>
      <Drawer
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
          },
        }}
        variant="persistent"
        anchor="left"
        open={open}
      >
        <DrawerHeader>
          <IconButton onClick={handleDrawerClose}>
            {theme.direction === 'ltr' ? <ChevronLeftIcon /> : <ChevronRightIcon />}
          </IconButton>
        </DrawerHeader>
        <Divider />
        <List>
          {['시나리오 관리'].map((text, index) => (
            <ListItem key={text} disablePadding>
              <ListItemButton>
                <ListItemIcon>
                  {index % 2 === 0 ? <InboxIcon /> : <MailIcon />}
                </ListItemIcon>
                <ListItemText primary={text} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
        <Divider />
      </Drawer>
      <Main open={open}>
        <DrawerHeader />
        <Box display="flex" justifyContent="flex-end" padding="20px" gap="20px"> 
          <Button color="primary" variant="outlined" disabled={isRunPending} onClick={handleScenarioRunAll}>시나리오 전체 실행</Button>

          <Button color="primary" variant='contained' onClick={handleScenarioAdd}>시나리오 추가</Button>
        </Box>
        <TableContainer component={Paper}>
      <Table sx={{ minWidth: 650 }} aria-label="simple table">
        <TableHead>
          <TableRow>
            <TableCell align="center">시나리오 이름</TableCell>
            <TableCell align="center">상태</TableCell>
            <TableCell align="center">관리</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(scenarioList)?.map((scenario) => (
            <TableRow
              key={scenario._id}
              sx={{ '&:last-child td, &:last-child th': { border: 0 } }}
            >
              <TableCell align="center" component="th" scope="row">
                {scenario.scenario_name}
              </TableCell>
              <TableCell align="center"><StatusIcon status={scenario.run_status}/></TableCell>
              <TableCell align="center" >
                <Box display="flex" gap="20px" justifyContent="center">
                  <Button color="primary" variant="contained" onClick={() => {
                    router.push(`/${scenario._id}`)
                  }}>수정</Button>
                  <Button color="error" variant="contained">삭제</Button>
                </Box>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
    
      </Main>
    </Box>
    <AddDialog open={isModalOpen} onClose={() => {setIsModalOpen(false)}}/>
    </>
  );
}
interface DialogProps {
  open: boolean;
  onClose: () => void;
}

const AddDialog:React.FC<DialogProps> = ({open, onClose}) => {
  const queryClient= useQueryClient();

  const { mutate } = useMutation({"mutationFn": async (name: string) => {
    await axios.post("http://127.0.0.1:5000/e2e/scenarios",{scenario_name: name});
  }});
  const [name, setName] = useState("");
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setName(e.target.value);
  }
  const handleAdd = () => {
    mutate(name,{
      onSuccess:() => {
        queryClient.invalidateQueries({queryKey: ['scenarios']})
        onClose();
      }
    })
  }
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xl" sx={{padding:"20px"}} >
      <DialogTitle>시나리오 추가</DialogTitle>
      <Box padding="20px" width="400px">
        <TextField label="시나리오 이름" fullWidth onChange={handleChange} value={name}/>
      </Box>
      <DialogActions>
        <Button disabled={!name} variant="contained" color="primary" onClick={handleAdd}>추가</Button>
        <Button variant="contained" color="error" onClick={onClose}>취소</Button>
      </DialogActions>
    </Dialog>
  )

}


// [
//   {id: "1", name: "로그인", run_status: "failed"},
//   {id: "2", name: "회원가입", run_status: "success"},
//   {id: "3", name: "탈퇴", run_status: "loading"},
//   {id: "4", name: "구매", run_status: "ready"},
// ]
// [
//   {
//     계층정보: "",
//     screenshot: "",
//     status:""
//   },
//   {
//     description:"",
//     status:"",
//   },
//   {
//     계층정보: "",
//     screenshot: "",
//     status:""
//   },
//   {
//     description:"",
//     status:"",
//   },
// ]